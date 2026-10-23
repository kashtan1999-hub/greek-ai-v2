"""Serialize in-process state mutations for each Telegram student."""
import asyncio
from functools import wraps
_locks={}

def serialize_student(handler):
    @wraps(handler)
    async def guarded(event,*args,**kwargs):
        user=getattr(event,'from_user',None)
        if not user:return await handler(event,*args,**kwargs)
        entry=_locks.setdefault(user.id,[asyncio.Lock(),0])
        entry[1]+=1
        try:
            async with entry[0]:
                return await handler(event,*args,**kwargs)
        finally:
            entry[1]-=1
            if not entry[1]:_locks.pop(user.id,None)
    return guarded
