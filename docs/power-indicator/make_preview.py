"""Render a dimensioned placement concept; not a PCB fabrication design."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
S = 2
WIDTH, HEIGHT = 1040, 960
BOARD_WIDTH_MM, BOARD_HEIGHT_MM = 50, 60
PX_PER_MM = 10
BOARD_X, BOARD_Y = 120, 190
BOARD_RIGHT = BOARD_X + BOARD_WIDTH_MM * PX_PER_MM
BOARD_BOTTOM = BOARD_Y + BOARD_HEIGHT_MM * PX_PER_MM
# This value is intentionally unknown. 4700 uF does not specify body dimensions.
CAP_BODY_DIAMETER_MM = None
CAP_BODY_HEIGHT_MM = None
CAP_LEAD_PITCH_MM = None

im = Image.new('RGB', (WIDTH*S, HEIGHT*S), '#f0f3f4')
d = ImageDraw.Draw(im)
def font(size, bold=False):
    path = r'C:\Windows\Fonts\segoeuib.ttf' if bold else r'C:\Windows\Fonts\segoeui.ttf'
    return ImageFont.truetype(path, round(size*S))
def box(b, fill, outline=None, width=1, radius=0):
    b = tuple(round(v*S) for v in b)
    if radius:
        d.rounded_rectangle(b, round(radius*S), fill=fill, outline=outline, width=round(width*S))
    else:
        d.rectangle(b, fill=fill, outline=outline, width=round(width*S))
def line(points, fill, width=1):
    d.line([(round(x*S),round(y*S)) for x,y in points], fill=fill, width=round(width*S))
def circle(x,y,r,fill,outline=None,width=1):
    d.ellipse(tuple(round(v*S) for v in (x-r,y-r,x+r,y+r)),fill=fill,outline=outline,width=round(width*S))
def text(x,y,t,size=18,fill='#182c33',bold=False,anchor=None):
    d.text((round(x*S),round(y*S)), t, font=font(size,bold),fill=fill,anchor=anchor)
def centered(x,y,t,size=18,fill='#edf8ef',bold=False):
    text(x,y,t,size,fill,bold,'mm')
def point(x_mm, y_mm):
    return BOARD_X+x_mm*PX_PER_MM, BOARD_Y+y_mm*PX_PER_MM

def terminal(x,y,ref,title,pinlabels,labels_side='right'):
    box((x-28,y-43,x+28,y+43),'#1677a3','#7cbed4',2,5)
    for yy in (y-21,y+21):
        circle(x,yy,11,'#b7c6c9','#788b8e',1)
        line([(x-6,yy+3),(x+6,yy-3)],'#33444b',3)
    centered(x,y-66,ref,19,bold=True)
    centered(x,y+67,title,16,bold=True)
    label_x = x+38 if labels_side=='right' else x-38
    anchor = 'lm' if labels_side=='right' else 'rm'
    for yy,label in zip((y-21,y+21), pinlabels):
        text(label_x,yy,label,14,'#e4f3e8',True,anchor)

text(64,34,'POWER INDICATOR SUPPLY',30,bold=True)
text(65,82,'Revisi penempatan  |  papan 5 x 6 cm  |  tampak atas',19,'#52656d')
# Board outline has an exact 50:60 aspect ratio, not an arbitrary illustration.
box((BOARD_X,BOARD_Y,BOARD_RIGHT,BOARD_BOTTOM),'#174b38','#103628',2,9)
box((BOARD_X+12,BOARD_Y+12,BOARD_RIGHT-12,BOARD_BOTTOM-12),None,'#70a583',1,6)
# Dimension lines terminate at the outside edges of the board.
DIM_COLOR = '#445b65'
for x in (BOARD_X,BOARD_RIGHT):
    line([(x,180),(x,134)],DIM_COLOR)
line([(BOARD_X,149),(BOARD_RIGHT,149)],DIM_COLOR,2)
line([(BOARD_X+8,144),(BOARD_X,149),(BOARD_X+8,154)],DIM_COLOR,2)
line([(BOARD_RIGHT-8,144),(BOARD_RIGHT,149),(BOARD_RIGHT-8,154)],DIM_COLOR,2)
box((299,130,441,169),'#f0f3f4')
centered(370,149,'50 mm / 5 cm',18,DIM_COLOR,True)
for y in (BOARD_Y,BOARD_BOTTOM):
    line([(109,y),(62,y)],DIM_COLOR)
line([(78,BOARD_Y),(78,BOARD_BOTTOM)],DIM_COLOR,2)
line([(73,BOARD_Y+8),(78,BOARD_Y),(83,BOARD_Y+8)],DIM_COLOR,2)
line([(73,BOARD_BOTTOM-8),(78,BOARD_BOTTOM),(83,BOARD_BOTTOM-8)],DIM_COLOR,2)
# Rotated dimension label remains readable at ordinary preview size.
label = Image.new('RGBA', (192*S,34*S),(0,0,0,0))
ld = ImageDraw.Draw(label)
ld.text((96*S,17*S),'60 mm / 6 cm',font=font(18,True),fill=DIM_COLOR,anchor='mm')
label = label.rotate(90,expand=True)
im.paste(label,(round((78-17)*S),round((490-96)*S)),label)

text(152,221,'APD CHECKER',23,'#eff8ee',True)
text(152,254,'12 V DC  /  PLACEMENT DRAFT',15,'#d5e9d9')
# Mounting holes are deliberately omitted pending mechanical confirmation.
# J3 occupies the former output area; J2 occupies the former switch area.
terminal(*point(6.5,17.5),'J1','INPUT',('+','-'))
terminal(*point(6.5,43.5),'J3','SAKLAR',('A','B'))
terminal(*point(43,17.5),'J2','OUTPUT',('+','-'),'left')

lx,ly = point(19,17.5)
centered(lx,ly-66,'LED1',18,bold=True)
circle(lx,ly,23,'#71312e','#ebdddd',2)
circle(lx-6,ly-7,10,'#b85246')
centered(lx,ly+67,'LED*',16)

rx,ry = point(30,17.5)
centered(rx,ry-66,'R1',18,bold=True)
line([(rx-39,ry),(rx+39,ry)],'#cbd5cc',4)
for px in (rx-40,rx+40):
    circle(px,ry,6,'#d9b85c'); circle(px,ry,2.5,'#17272b')
box((rx-28,ry-11,rx+28,ry+11),'#e3cba5','#c6ac84',1,3)
for offset,color in ((-21,'#b43832'),(-11,'#b43832'),(0,'#a3312a'),(20,'#b19843')):
    box((rx+offset,ry-11,rx+offset+3,ry+11),color)
centered(rx,ry+67,'2k2*',16)

# C1 is an explicitly unmeasured placeholder, NOT an exact physical footprint.
cx,cy = point(31,43.5)
centered(cx,cy-106,'C1  /  ELCO',18,bold=True)
circle(cx,cy,82,'#324247','#e4c181',2)
circle(cx,cy,70,'#526267','#718289',2)
line([(cx-45,cy-45),(cx+45,cy+45)],'#76898d',2)
line([(cx-45,cy+45),(cx+45,cy-45)],'#76898d',2)
centered(cx,cy-17,'4700 uF',22,'#f6f9f7',True)
centered(cx,cy+14,'DIAMETER ?',15,'#f6f9f7',True)
centered(cx,cy+107,'UKURAN BELUM DIUKUR',14,'#ffe4ac',True)
centered(370,765,'BELUM ADA JALUR TEMBAGA',16,'#ecedd2',True)

text(665,211,'UKURAN PAPAN',21,bold=True)
text(665,252,'50 x 60 mm',29,bold=True)
text(665,299,'Horizontal 50 mm; vertikal 60 mm.',17,'#52656d')
text(665,330,'Outline proporsional, bukan cetak 1:1.',17,'#52656d')
text(665,392,'POSISI BARU',21,bold=True)
text(665,435,'J1 INPUT + J3 SAKLAR: sisi kiri.',17)
text(665,466,'J2 OUTPUT: sisi kanan atas.',17)
text(665,534,'C1: DATA YANG DIBUTUHKAN',19,bold=True)
text(665,576,'Diameter badan: ___ mm',18)
text(665,610,'Tinggi badan: ___ mm',18)
text(665,644,'Jarak pusat kedua kaki: ___ mm',18)
text(665,678,'Rating tegangan / seri: ___',18)
text(665,731,'Ukuran elco tidak ditebak.',19,'#9c352c',True)
text(665,764,'Bentuk C1 masih placeholder.',18,'#52656d')

text(120,826,'* Ukuran LED, resistor, konektor, dan footprint belum dikonfirmasi.',17,'#52656d')
text(120,859,'J3 = terminal ke saklar eksternal; bukan footprint saklar final.',17,'#52656d')
text(120,899,'DRAFT - TIDAK UNTUK FABRIKASI / PERAKITAN',20,'#9c352c',True)

assert BOARD_RIGHT-BOARD_X == BOARD_WIDTH_MM*PX_PER_MM
assert BOARD_BOTTOM-BOARD_Y == BOARD_HEIGHT_MM*PX_PER_MM
im.resize((WIDTH,HEIGHT),Image.Resampling.LANCZOS).save(HERE/'placement-preview.png')
print(HERE/'placement-preview.png')
