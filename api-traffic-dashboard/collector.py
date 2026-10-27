"""Import into your API client program; no provider keys required here."""
import json
from urllib.request import Request, urlopen
from datetime import datetime, timezone, timedelta

def report_usage(provider, request_id, model, usage, project='default', time=None, port=8787):
    """Map OpenAI-compatible response usage. Missing fields stay unknown.
    Returns False on collection failure. Call once per actual billable API request.
    """
    try:
        usage=usage or {}
        details=usage.get('prompt_tokens_details') or usage.get('input_tokens_details') or {}
        cached=usage.get('prompt_cache_hit_tokens',details.get('cached_tokens'))
        event=dict(id=request_id,provider=provider,model=model,project=project,
                   time=time or datetime.now(timezone(timedelta(hours=8))).isoformat(),
                   input_tokens=usage.get('prompt_tokens',usage.get('input_tokens')),
                   output_tokens=usage.get('completion_tokens',usage.get('output_tokens')),
                   cached_tokens=cached,requests=1)
        req=Request(f'http://127.0.0.1:{int(port)}/api/events',data=json.dumps({'events':[event]}).encode(),headers={'Content-Type':'application/json'})
        with urlopen(req,timeout=3) as response:
            return response.status==200
    except (OSError,ValueError,TypeError):
        return False
