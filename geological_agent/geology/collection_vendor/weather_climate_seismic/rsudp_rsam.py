# Adaptation: isolated upstream function bodies with import/class glue added.
# Ian Nesbitt, Richard Boaz, Justin Long; Raspberry Shake, S.A.
# Original algorithms unchanged; full upstream license in licenses/.
import statistics
class RSAMKernel:

	def _rsam(self):
		"""
		Run the RSAM analysis
		"""
		arr = [abs(el) for el in self.stream[0].data]
		meanv = statistics.mean(arr)
		medianv = statistics.median(arr)
		minv = min(arr)
		maxv = max(arr)
		self.rsam = [meanv, medianv, minv, maxv]


