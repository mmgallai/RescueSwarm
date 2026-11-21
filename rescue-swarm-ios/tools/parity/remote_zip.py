"""Read selected ZIP members with verified CRC through HTTP byte ranges."""
import io,json,time,urllib.request,urllib.error,zipfile,hashlib
from pathlib import Path

URL='https://zenodo.org/api/records/5662351/files/heridal_keras_retinanet_voc.zip/content'
SIZE=8311735812

class RemoteZip(io.RawIOBase):
    def __init__(self): self.pos=0; self.blocks={}
    def seekable(self): return True
    def readable(self): return True
    def tell(self): return self.pos
    def seek(self,offset,whence=0):
        self.pos=offset if whence==0 else self.pos+offset if whence==1 else SIZE+offset
        if self.pos<0: raise ValueError('Negative seek')
        return self.pos
    def read(self,n=-1):
        n=min(SIZE-self.pos,n if n>=0 else SIZE-self.pos)
        if n<=0:return b''
        start=self.pos; stop=start+n
        for (a,b),data in self.blocks.items():
            if a<=start and stop<=b: self.pos=stop; return data[start-a:stop-a]
        # Cache nearby ZIP headers together with data to reduce request count.
        end=min(SIZE,max(stop,start+65536))
        for attempt in range(5):
            try:
                req=urllib.request.Request(URL,headers={'Range':f'bytes={start}-{end-1}'})
                with urllib.request.urlopen(req,timeout=60) as response:
                    assert response.status==206
                    assert response.headers['Content-Range']==f'bytes {start}-{end-1}/{SIZE}'
                    data=response.read()
                assert len(data)==end-start
                break
            except urllib.error.HTTPError as ex:
                if ex.code not in (429,500,502,503,504):raise
                if attempt==4:raise
                time.sleep(min(60,int(ex.headers.get('Retry-After','10'))))
        self.blocks[(start,end)]=data; self.pos=stop
        return data[:n]
