import ctypes
import ctypes.wintypes
import cv2
import numpy as np
from PIL import ImageGrab

COLORS = ("#ffffff", "#000000", "#fff200", "#ff00ff", "#00ffff", "#ff3b30", "#3478f6")


class TablePresenceTracker:
    def __init__(self, missing_frames=2, present_frames=2):
        self.missing_frames = missing_frames
        self.present_frames = present_frames
        self.seen_table = False
        self.away = False
        self.missing_count = 0
        self.present_count = 0

    def update(self, table_found):
        if table_found:
            self.missing_count = 0
            self.present_count += 1
            if self.present_count < self.present_frames:
                return None
            if not self.seen_table:
                self.seen_table = True
                return "found"
            if self.away:
                self.away = False
                return "switched"
            return None
        self.present_count = 0
        self.missing_count += 1
        if self.seen_table and not self.away and self.missing_count >= self.missing_frames:
            self.away = True
            return "left"
        return None

def enable_dpi_awareness():
    try: ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        try: ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError): ctypes.windll.user32.SetProcessDPIAware()

def monitors():
    regions=[]
    callback_type=ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p,ctypes.POINTER(ctypes.wintypes.RECT),ctypes.c_ssize_t)
    @callback_type
    def callback(_,__,rect,___): regions.append((rect.contents.left,rect.contents.top,rect.contents.right,rect.contents.bottom)); return True
    ctypes.windll.user32.EnumDisplayMonitors(None,None,callback,0)
    return regions

def capture_desktop():
    regions=monitors()
    if not regions: return None,(0,0)
    left=min(r[0] for r in regions); top=min(r[1] for r in regions); right=max(r[2] for r in regions); bottom=max(r[3] for r in regions)
    desktop=np.asarray(ImageGrab.grab(all_screens=True).convert("RGB"))
    if desktop.shape[1] != right-left or desktop.shape[0] != bottom-top: desktop=cv2.resize(desktop,(right-left,bottom-top),interpolation=cv2.INTER_AREA)
    return desktop,(left,top)

def detect_table(image):
    hsv=cv2.cvtColor(cv2.cvtColor(np.asarray(image),cv2.COLOR_RGB2BGR),cv2.COLOR_BGR2HSV)
    mask=cv2.inRange(hsv,np.array([66,90,55]),np.array([92,255,255]))
    size=max(9,round(min(mask.shape)*.018)|1)
    connected=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,cv2.getStructuringElement(cv2.MORPH_RECT,(size,size)))
    contours,_=cv2.findContours(connected,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    choices=[]
    for contour in contours:
        x,y,width,height=cv2.boundingRect(contour)
        raw=mask[y:y+height,x:x+width]; rows=np.flatnonzero(np.count_nonzero(raw,axis=1)/max(width,1)>=.35)
        if rows.size: y+=int(rows[0]); height=int(rows[-1]-rows[0]+1)
        raw=mask[y:y+height,x:x+width]; columns=np.flatnonzero(np.count_nonzero(raw,axis=0)/max(height,1)>=.35)
        if columns.size: x+=int(columns[0]); width=int(columns[-1]-columns[0]+1)
        ratio=width/max(height,1)
        if width<220 or height<440 or not .28<=ratio<=.80: continue
        region=mask[y:y+height,x:x+width]; coverage=np.count_nonzero(region)/region.size
        if coverage<.42: continue
        edge=max(2,round(min(width,height)*.012))
        edge_coverage=np.mean((np.count_nonzero(region[:edge])/region[:edge].size,np.count_nonzero(region[-edge:])/region[-edge:].size,np.count_nonzero(region[:,:edge])/region[:,:edge].size,np.count_nonzero(region[:,-edge:])/region[:,-edge:].size))
        choices.append((coverage+edge_coverage+width*height/mask.size,[x,y,x+width,y+height]))
    detected=max(choices,default=(None,None),key=lambda item:item[0])[1]
    return expand_table_bbox(detected,image.shape[1],image.shape[0]) if detected else None


def expand_table_bbox(bbox,image_width,image_height,reference=(888,1920)):
    x1,y1,x2,y2=map(int,bbox)
    reference_width,reference_height=reference
    target_height=round((x2-x1)*reference_height/reference_width)
    if target_height<=y2-y1: return [x1,y1,x2,y2]
    full_y1=max(0,y2-target_height)
    full_y2=min(image_height,full_y1+target_height)
    if full_y2-full_y1<target_height: full_y1=max(0,full_y2-target_height)
    return [max(0,x1),full_y1,min(image_width,x2),full_y2]

def border_color(image,bbox,border=6):
    pixels=np.asarray(image); x1,y1,x2,y2=bbox; inset=border+2; outside=border*2
    strips=(pixels[y1:min(y1+inset,y2),x1:x2],pixels[max(y2-inset,y1):y2,x1:x2],pixels[y1:y2,x1:min(x1+inset,x2)],pixels[y1:y2,max(x2-inset,x1):x2],pixels[max(0,y1-outside):y1,x1:x2],pixels[y2:min(pixels.shape[0],y2+outside),x1:x2],pixels[y1:y2,max(0,x1-outside):x1],pixels[y1:y2,x2:min(pixels.shape[1],x2+outside)])
    samples=[np.median(strip.reshape(-1,3),axis=0) for strip in strips if strip.size]
    def distance(color):
        rgb=np.array([int(color[i:i+2],16) for i in (1,3,5)])
        return min(float(np.linalg.norm(rgb-sample)) for sample in samples) if samples else 0
    return max(COLORS,key=distance)
