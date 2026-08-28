from dataclasses import dataclass,field


@dataclass
class ScannerBuffer:
    """Reconoce ráfagas HID terminadas en Enter sin asumir longitud fija."""
    max_gap:float=0.12
    max_average:float=0.08
    min_length:int=6
    _chars:list[str]=field(default_factory=list)
    _times:list[float]=field(default_factory=list)

    def reset(self):self._chars.clear();self._times.clear()

    def character(self,value:str,now:float):
        if len(value)!=1 or not (value.isalnum() or value in "-_."):
            self.reset();return
        if self._times and now-self._times[-1]>self.max_gap:self.reset()
        self._chars.append(value);self._times.append(now)

    def finish(self,now:float):
        if len(self._chars)<self.min_length or not self._times:self.reset();return None
        elapsed=max(0.001,self._times[-1]-self._times[0]);average=elapsed/max(1,len(self._chars)-1)
        recent=now-self._times[-1]<=self.max_gap;value="".join(self._chars) if recent and average<=self.max_average else None
        self.reset();return value
