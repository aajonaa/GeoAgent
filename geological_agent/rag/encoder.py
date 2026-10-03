"""Private CPU encoder service. No LLM calls, network fetches or remote model code."""
import json
import os
from pathlib import Path
import socketserver
from http.server import BaseHTTPRequestHandler
from threading import Lock
from .store import chunks

def main():
    import numpy as np
    import torch
    from sentence_transformers import SentenceTransformer, CrossEncoder
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    root=Path(os.environ["GEOTOOL_ENCODER_MODELS"])
    manifest=json.loads((root/"manifest.json").read_text())
    embed=SentenceTransformer(str(root/"embedding"),device="cpu",local_files_only=True,
                              trust_remote_code=False,model_kwargs={"use_safetensors":True})
    ranker=CrossEncoder(str(root/"reranker"),device="cpu",local_files_only=True,
                        trust_remote_code=False,model_kwargs={"use_safetensors":True},max_length=512)
    lock=Lock()

    def encode(texts,query=False):
        output=[]
        for text in texts:
            # Encode all query windows, with an explicit mean aggregation, not
            # silently truncating a long user request to the model limit.
            prefix="query: " if query else "passage: "
            windows=[text[i:i+350] for i in range(0,len(text),350)] or [""]
            values=embed.encode([prefix+x for x in windows],normalize_embeddings=True,
                                show_progress_bar=False,batch_size=16)
            value=values.mean(axis=0)
            value=value/np.linalg.norm(value)
            output.append(value.tolist())
        return output

    def split_text(text):
        todo=chunks(text)
        result=[]
        while todo:
            part=todo.pop(0)
            count=len(embed.tokenizer.encode("passage: "+part["text"],add_special_tokens=True))
            rcount=len(ranker.tokenizer.encode(part["text"],add_special_tokens=True))
            if max(count,rcount)>380 and len(part["text"])>1:
                mid=len(part["text"])//2
                left={"start_char":part["start_char"],"end_char":part["start_char"]+mid,"text":part["text"][:mid]}
                right={"start_char":left["end_char"],"end_char":part["end_char"],"text":part["text"][mid:]}
                todo[0:0]=[left,right]
            else: result.append(part)
        return result

    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_POST(self):
            try:
                n=int(self.headers.get("Content-Length","0"))
                if not 0<n<=1024*1024: raise ValueError("Request size")
                p=json.loads(self.rfile.read(n))
                with lock,torch.inference_mode():
                    if self.path=="/embed":
                        texts=p["texts"]
                        if not isinstance(texts,list) or not 1<=len(texts)<=32 or any(not isinstance(x,str) or len(x)>24000 for x in texts):
                            raise ValueError("Embedding input")
                        result={"vectors":encode(texts,bool(p.get("query"))),"aggregation":"normalized mean of 350-character windows"}
                    elif self.path=="/ingest":
                        text=p["text"]
                        if not isinstance(text,str) or not 0<len(text)<=120000: raise ValueError("Document length")
                        parts=split_text(text)
                        # Passage chunks already token-bounded. Encode once, not
                        # window-averaged, so indexed vectors match passage semantics.
                        vectors=embed.encode(["passage: "+x["text"] for x in parts],normalize_embeddings=True,
                            batch_size=16,show_progress_bar=False).tolist()
                        result={"chunks":parts,"vectors":vectors}
                    elif self.path=="/rerank":
                        query,passages=p["query"],p["passages"]
                        if not isinstance(query,str) or len(query)>24000 or not isinstance(passages,list) or not 1<=len(passages)<=32 or any(not isinstance(x,str) or len(x)>1000 for x in passages):
                            raise ValueError("Reranking input")
                        ids=ranker.tokenizer.encode(query,add_special_tokens=False)
                        used=ids[:96]
                        query_window=ranker.tokenizer.decode(used,skip_special_tokens=True)
                        scores=ranker.predict([(query_window,text) for text in passages],batch_size=16,
                                              show_progress_bar=False,activation_fn=torch.nn.Identity())
                        result={"scores":scores.tolist(),"model":manifest["reranker"]["model"]+"@"+manifest["reranker"]["revision"],
                                "query_tokens_used":len(used),"query_tokens_total":len(ids)}
                    elif self.path=="/health":
                        result={"ok":True,"models":{k:{"model":v["model"],"revision":v["revision"]} for k,v in manifest.items()}}
                    else:
                        self.send_error(404); return
                data=json.dumps(result,allow_nan=False).encode()
                self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(data)))
                self.end_headers(); self.wfile.write(data)
            except Exception as exc:
                # No document text, model paths or credentials in public errors.
                self.send_error(400,"Encoder rejected request: "+type(exc).__name__)
    socket=Path(os.environ["GEOTOOL_ENCODER_SOCKET"])
    socket.parent.mkdir(parents=True,exist_ok=True)
    if socket.exists(): socket.unlink()
    os.umask(0o077)
    with socketserver.UnixStreamServer(str(socket),Handler) as server:
        os.chmod(socket,0o600)
        print("Knowledge CPU encoder ready",flush=True)
        server.serve_forever()

if __name__=="__main__":
    main()
