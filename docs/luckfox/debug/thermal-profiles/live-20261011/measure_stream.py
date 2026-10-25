import cv2,time,json,os
os.environ['OPENCV_FFMPEG_CAPTURE_OPTIONS']='rtsp_transport;tcp'
cap=cv2.VideoCapture('rtsp://127.0.0.1:18554/live/0',cv2.CAP_FFMPEG,[cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,5000,cv2.CAP_PROP_READ_TIMEOUT_MSEC,5000])
print(json.dumps({'opened':cap.isOpened(),'advertised_fps':cap.get(cv2.CAP_PROP_FPS)}),flush=True)
# Discard startup buffering for 3 seconds; PC decodes only, no saved images.
start=time.monotonic();first=None;last=None;n=0
while cap.isOpened() and time.monotonic()-start < 15:
 ok,frame=cap.read()
 if not ok: break
 t=time.monotonic()
 if t-start<3: continue
 if first is None: first=t
 last=t;n+=1
cap.release()
print(json.dumps({'frames_decoded_after_warmup':n,'approx_delivery_fps':(n-1)/(last-first) if n>1 else None,'saved_images':False}),flush=True)
