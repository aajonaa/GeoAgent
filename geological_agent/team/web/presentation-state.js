'use strict';
(() => {
  function latestRequest() {
    let sequence = 0;
    return {begin: () => ++sequence, current: token => token === sequence};
  }
  const api = {latestRequest};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else window.GeoPresentationState = api;
})();
