"""C3 route follower, closed loop offline (no game): the real follower source
drives a simple car model along the 52 road-graph nodes of the crossing.

One number per direction: the largest distance (m) from the node polyline,
the crossing checker's own measure, limit 12.0 m (the road's own centre line
is up to 5.23 m from that polyline). A run that spins, is short or off-axis
at the lip, meets a gap wall or the bridge entrance post, or never arrives
counts as 99.
  follower without the dead-zone term: forward 99, reverse 99 (off the road
                                       before the bridge, short at the lip)
  this follower:                       forward 5.32, reverse 5.29 (PASS)
The follower before this work scores 99 / 99 here too (29.40 m then the
post; 29.31 m then a gap wall); live it measured 14.56 m at the 8752 bend.

Car model, from follower traces: no turn for a stick under 0.18, then
0.175 /m of path curvature per unit stick up to 25 m/s, falling with speed
squared above that (0.07 at 37 m/s, 0.044 at 41); a 0.15 s lag; 16 m/s2
sideways at most (a demand above 1.5x that for 0.3 s is a spin). The gap
needs 43 m/s along the lip axis, a heading within 5 degrees and the car's
centre between the gap walls (narrow side decoded, wide side where forward
run 2 touched); the entrance post is where forward run 1 struck it (49.5 m
before the near lip, 4.3 m left of the axis). This follower must also pass
at dead zone 0.15 and 0.21 and at lag 0.3 s (5.09 to 6.07 m). The model has
no weave: at 36 m/s the car wove up to 9.8 m off the path live (forward run
2, reverse run 1) where this model stays within 8 m; hence 25 m/s roads.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
FOLLOWER = HERE / 'private_runtime/carbon_c3drive.h'
LIMIT = 12.0
# Stick dead zone, curvature per unit stick beyond it (1/m), response lag (s).
CARS = (('0.18', '0.175', '0.15'), ('0.15', '0.12', '0.15'), ('0.21', '0.2', '0.15'), ('0.18', '0.175', '0.3'))
# Forward order 8739..8754, 8988..9022, 1534: node X Y Z, then its segment to
# the next node: starts-here flag, handles +12 +14, control bytes +16..+21.
ROUTE = """
 -3001.718 188.430 7827.218 1 2311 2314 0 -8 126 -74 7 -102
 -3025.853 192.993 7779.935 1 2815 2311 -63 -5 110 0 8 -126
 -3001.596 196.886 7721.664 1 2338 2816 -50 -8 115 63 5 -110
 -2961.662 197.979 7668.274 1 2916 2338 -4 -21 125 50 8 -115
 -2958.617 204.521 7623.936 1 2873 2916 -27 -19 122 4 21 -125
 -2956.974 220.392 7536.726 1 2526 2873 -93 1 85 27 19 -122
 -2929.982 224.546 7497.180 1 3709 2526 -106 16 67 93 -1 -85
 -2871.735 219.006 7458.550 1 4157 3709 -98 14 78 106 -16 -67
 -2788.008 203.069 7406.539 1 4554 4157 -80 -1 97 98 -14 -78
 -2723.885 197.965 7340.571 1 5075 4554 -71 -7 104 80 1 -97
 -2655.053 205.223 7245.935 1 4696 4696 -68 0 107 68 0 -107
 -2597.129 205.235 7155.242 1 5514 6104 -58 0 112 69 -2 -106
 -2524.089 202.835 7035.264 1 4357 5514 -24 -2 124 58 0 -112
 -2480.318 205.521 6931.456 1 3279 4357 36 -1 121 24 2 -124
 -2485.543 206.664 6839.598 1 2847 3279 92 -1 87 -36 1 -121
 -2523.409 207.302 6787.646 1 606 606 72 -3 105 -72 3 -105
 -2531.269 207.683 6776.217 1 3157 3157 89 -3 91 -89 3 -91
 -2581.832 209.542 6724.644 1 1832 1832 80 -16 97 -80 16 -97
 -2608.235 214.893 6692.499 1 1832 1832 80 -13 97 -80 13 -97
 -2634.781 219.310 6660.341 1 3197 3197 71 2 105 -71 -2 -105
 -2675.625 218.379 6599.636 1 1820 1820 61 9 111 -61 -9 -111
 -2695.785 215.371 6563.308 1 3110 3110 49 25 114 -49 -25 -114
 -2723.311 201.472 6499.159 1 1740 1740 38 29 118 -38 -29 -118
 -2735.138 192.323 6462.246 1 1740 1740 39 18 120 -39 -18 -120
 -2747.266 186.659 6424.733 1 1741 1741 39 10 120 -39 -10 -120
 -2759.582 183.440 6386.973 1 1742 1742 40 10 120 -40 -10 -120
 -2772.005 180.224 6349.213 1 1744 1744 40 10 120 -40 -10 -120
 -2784.536 177.010 6311.456 1 1745 1745 40 10 120 -40 -10 -120
 -2797.174 173.798 6273.700 1 1747 1747 40 10 120 -40 -10 -120
 -2809.919 170.589 6235.947 1 1748 1748 41 10 120 -41 -10 -120
 -2822.771 167.382 6198.196 1 1749 1749 41 10 120 -41 -10 -120
 -2835.729 164.177 6160.449 1 1751 1751 41 10 120 -41 -10 -120
 -2848.794 160.975 6122.706 1 1752 1752 42 10 120 -42 -10 -120
 -2861.966 157.776 6084.967 1 1753 1753 42 10 119 -42 -10 -119
 -2875.243 154.579 6047.233 1 1755 1755 42 10 119 -42 -10 -119
 -2888.627 151.384 6009.504 1 1756 1756 43 10 119 -43 -10 -119
 -2902.117 148.192 5971.781 1 1757 1757 43 10 119 -43 -10 -119
 -2915.712 145.002 5934.064 1 1758 1758 43 10 119 -43 -10 -119
 -2929.413 141.815 5896.354 1 1760 1760 44 10 119 -44 -10 -119
 -2943.220 138.630 5858.650 1 1761 1761 44 10 119 -44 -10 -119
 -2957.132 135.448 5820.954 1 1762 1762 44 10 119 -44 -10 -119
 -2971.148 132.268 5783.266 1 1764 1764 44 10 119 -44 -10 -119
 -2985.270 129.091 5745.586 1 1765 1765 45 10 118 -45 -10 -118
 -2999.497 125.917 5707.915 1 1766 1766 45 10 118 -45 -10 -118
 -3013.828 122.744 5670.253 1 1767 1767 45 10 118 -45 -10 -118
 -3028.263 119.575 5632.601 1 1768 1768 46 10 118 -46 -10 -118
 -3042.803 116.408 5594.959 1 1770 1770 46 10 118 -46 -10 -118
 -3057.447 113.243 5557.328 1 1771 1771 46 10 118 -46 -10 -118
 -3072.195 110.081 5519.707 1 1772 1772 47 10 118 -47 -10 -118
 -3087.047 106.921 5482.098 1 1773 1773 47 10 118 -47 -10 -118
 -3102.002 103.764 5444.501 1 825 825 122 -2 37 -122 2 -37
 -3120.068 104.100 5439.030 0 0 0 0 0 0 0 0
"""

HARNESS = r"""
#include <math.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static uint8_t *G;
#define M8(a) (*(uint8_t *)(G+(uint32_t)(a)))
#define M16(a) (*(uint16_t *)(G+(uint32_t)(a)))
#define M32(a) (*(uint32_t *)(G+(uint32_t)(a)))
#define MF32(a) (*(float *)(G+(uint32_t)(a)))
static const char *gptr(uint32_t a) {return (const char *)G+a;}
static int diag_on, wheels = 4;
static void diag_event(const char *format,...) {(void)format;}
static int carbon_census_wheels(void) {return wheels;}
#include "carbon_c3drive.h"
static const double route[52][12] = {
ROWS
};
static double offset(double x,double z,int direction) {
 double best=1e30;
 for(unsigned i=0;i<51;++i) {
  const double *a=route[i],*b=route[i+1];
  double dx=b[0]-a[0],dz=b[2]-a[2],t=fmax(0.,fmin(1.,((x-a[0])*dx+(z-a[2])*dz)/(dx*dx+dz*dz)));
  best=fmin(best,hypot(x-a[0]-t*dx,z-a[2]-t*dz));
 }
 (void)direction;return best;
}
int main(int argc,char **argv) {
 int direction=argc>1&&!strcmp(argv[1],"reverse")?-1:1;
 double dead=argc>2?atof(argv[2]):.18, slope=argc>3?atof(argv[3]):.175, lag=argc>4?atof(argv[4]):.15;
 G=calloc(1,16u<<20);
 setenv("NFS_CARBON_C3_ROUTE",direction>0?"forward":"reverse",1);setenv("BOOT_AUTODRIVE","1",1);
 setenv("BOOT_PAD","sim",1);setenv("NFS_CARBON_SKIPFE","1",1);setenv("NFS_CARBON_SKIPFE_START","x",1);
 M32(0xB77EC8)=0x400000;M32(0xB77ECC)=0x600000;
 for(unsigned i=0;i<52;++i) {
  uint32_t node=0x400000+32*carbon_c3drive_node(i,1);
  for(unsigned k=0;k<3;++k) MF32(node+4*k)=(float)route[i][k];
  if(i<51) {
   uint32_t s=0x600000+22*i,a=carbon_c3drive_node(i,1),b=carbon_c3drive_node(i+1,1);
   M16(s)=route[i][3]?a:b;M16(s+2)=route[i][3]?b:a;
   M16(s+12)=(uint16_t)route[i][4];M16(s+14)=(uint16_t)route[i][5];
   for(unsigned k=0;k<6;++k) M8(s+16+k)=(uint8_t)(int8_t)route[i][6+k];
   M16(node+18+2*M8(node+16))=i;M8(node+16)++;
   uint32_t next=0x400000+32*b;
   M16(next+18+2*M8(next+16))=i;M8(next+16)++;
  }
 }
 M32(0x5000)=0x6000;M32(0x6060)=0x6D7EA0;M32(0x504C)=0xC000;M32(0xC000)=0xD000;
 M32(0xD020)=0x6C6FF0;M32(0xC030)=0xE000;M32(0xE000)=0xF000;
 /* The car starts on the first city node of its side, facing along the road. */
 const double *from=route[direction>0?0:50],*to=route[direction>0?1:49];
 double x=from[0],z=from[2],heading=atan2(to[0]-from[0],to[2]-from[2]),speed=0,stick=0;
 double worst=0,time=0,lip_speed=0,lip_heading=0,excess=0;
 int spin=0,shortfall=0,flying=0,post=0,wall=0;
 uint64_t now=1000000000ull;
 for(;time<400.&&!carbon_c3drive_done&&!carbon_c3drive_arrived&&!spin&&!shortfall&&!post&&!wall;time+=1./60) {
  double along=(x+2635.271)*.5383-(z-7214.961)*.8428;
  int gap=along>.2&&along<34.05;
  if(gap&&!flying) {
   double course=direction*(.5383*sin(heading)-.8428*cos(heading));
   lip_speed=speed*course;
   lip_heading=acos(fmax(-1.,fmin(1.,course)))*57.29577951308232;
   if(lip_speed<43.||lip_heading>5.) shortfall=1;
  }
  /* Gap walls: decoded 134/31 on the narrow side less a car's half width; on
   * the wide side where forward run 2's yawed car touched (centre at 4.87). */
  if(gap||(flying&&!gap)) {
   double lat=(x+2635.271)*.8428+(z-7214.961)*.5383;
   if(lat<-4.5||lat>4.8) wall=1;
  }
  flying=gap;wheels=gap?0:4;
  /* The bridge entrance's left post: a car centred 4.3 m left of the lip axis,
   * 49.5 m before the near lip, struck it at 52 m/s (forward run 1). */
  if(along>-52.&&along<-47.&&(x+2635.271)*.8428+(z-7214.961)*.5383>=3.3) post=1;
  MF32(0xF010)=(float)x;MF32(0xF014)=0;MF32(0xF018)=(float)z;
  MF32(0xF020)=(float)(speed*sin(heading));MF32(0xF024)=0;MF32(0xF028)=(float)(speed*cos(heading));
  MF32(0xF090)=(float)sin(heading);MF32(0xF094)=0;MF32(0xF098)=(float)cos(heading);
  MF32(0xB4CFD8)=(float)time;M32(0xB4CFD4)++;now+=16666667ull;
  if(!carbon_c3drive_frame(0x5000,now)||!carbon_c3drive_active) {printf("C3FOLLOW inactive\n");return 2;}
  float lx=0,rt=0,lt=0;carbon_c3drive_pad(0,&lx,&rt,&lt);
  if(!gap) {
   stick+=(lx-stick)*fmin(1.,(1./60)/lag);
   /* Measured: no turn below the dead zone, then the bicycle slope; grip caps it. */
   /* Less wheel at speed: the slope falls with speed squared above 25 m/s
    * (forward runs 1 and 2: 0.07 /m at 37 m/s, 0.044 at 41). */
   double fade=fmin(1.,625./fmax(speed*speed,1.));
   double curvature=slope*fade*fmax(0.,fabs(stick)-dead)*(stick<0?-1:1),cap=16./fmax(speed*speed,1.);
   excess=fabs(curvature)>1.5*cap?excess+1./60:0;
   if(excess>.3) spin=1;
   heading+=speed*fmax(-cap,fmin(cap,curvature))/60;
   speed=fmax(0.,speed+(rt*fmin(10.5,330./fmax(speed,1.))-lt*12.-.3)/60);
  }
  x+=speed*sin(heading)/60;z+=speed*cos(heading)/60;
  if(argc>5&&M32(0xB4CFD4)%30==0)
   printf("t=%.1f x=%.1f z=%.1f speed=%.1f offset=%.2f lx=%.2f rt=%.2f lt=%.2f point=%u\n",
          time,x,z,speed,offset(x,z,direction),lx,rt,lt,carbon_c3drive_index);
  worst=fmax(worst,offset(x,z,direction));
 }
 int arrived=carbon_c3drive_arrived!=0;
 double number=spin||shortfall||post||wall||!arrived?99.:worst;
 printf("C3FOLLOW %s lateral=%.2f worst_offset=%.2f arrived=%d spin=%d short=%d post=%d wall=%d lip_speed=%.1f lip_heading=%.1f time=%.1f dead=%.2f slope=%.3f lag=%.2f\n",
        direction>0?"forward":"reverse",number,worst,arrived,spin,shortfall,post,wall,lip_speed,lip_heading,time,dead,slope,lag);
 return 0;
}
"""

# The follower without the dead-zone term, rebuilt from the current source.
OLD = (('#define CARBON_C3DRIVE_DEAD .18', '#define CARBON_C3DRIVE_DEAD 0.'),)


def rows():
    return ',\n'.join(' {' + ','.join(line.split()) + '}' for line in ROUTE.strip().splitlines())


def measure(tmp, name, source, car=('0.18', '0.175', '0.15')):
    (tmp / 'carbon_c3drive.h').write_text(source)
    binary = tmp / name
    subprocess.run(['clang', '-O1', '-I', str(tmp), str(tmp / 'harness.c'), '-o', str(binary), '-lm'], check=True)
    result = {}
    for direction in ('forward', 'reverse'):
        line = subprocess.run([str(binary), direction, *car], capture_output=True, text=True, check=True).stdout.strip()
        print(f'{name}: {line}')
        result[direction] = float(line.split('lateral=')[1].split()[0])
    return result


def main():
    follower = FOLLOWER.read_text()
    old = follower
    for new_text, old_text in OLD:
        assert new_text in old, new_text
        old = old.replace(new_text, old_text)
    with tempfile.TemporaryDirectory(prefix='private-c3follow-') as directory:
        tmp = Path(directory)
        (tmp / 'harness.c').write_text(HARNESS.replace('ROWS', rows()))
        before = measure(tmp, 'old', old)
        after = [measure(tmp, f'new-{i}', follower, car) for i, car in enumerate(CARS)]
    assert all(v > LIMIT for v in before.values()), before
    assert all(v <= LIMIT for result in after for v in result.values()), after
    print('C3FOLLOW PASS old forward %.2f reverse %.2f; new forward %.2f reverse %.2f (limit %.1f m)' % (
        before['forward'], before['reverse'], after[0]['forward'], after[0]['reverse'], LIMIT))
    return 0


if __name__ == '__main__':
    sys.exit(main())
