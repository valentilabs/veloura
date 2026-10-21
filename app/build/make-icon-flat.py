# Veloura's app icon (2026-10-21): the same flat seven-bar tile as Cadence's, recoloured: Deep Sable tile, Champagne
# Ivory to Electric Champagne bars with a muted brass raised edge. Writes veloura-icon.svg; make-icon.js renders it.
import math
cx,cy,a,n,N=512,506,412,5,720
def sq():
    p=[]
    for i in range(N):
        t=2*math.pi*i/N; c,s=math.cos(t),math.sin(t)
        x=cx+a*math.copysign(abs(c)**(2/n),c); y=cy+a*math.copysign(abs(s)**(2/n),s)
        p.append('%.1f %.1f'%(x,y))
    return 'M'+' L'.join(p)+'Z'
X=[185,283,381,479,577,675,773]; H=[161,315,474,412,230,358,199]; Y=[425.5,348.5,269,300,391,327,406.5]
def bars(dy): return ''.join('«rect x="%d" y="%s" width="66" height="%d" rx="33"/»'%(x,y+dy,h) for x,y,h in zip(X,Y,H))
hl=''.join('«path d="M%d %s A25 25 0 0 1 %d %s"/»'%(x+8,y+33,x+58,y+33) for x,y in zip(X,Y))
d=sq()
svg=f'''«svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024"»
«defs»
«linearGradient id="face" x1="0" y1="0" x2="0" y2="1"»«stop offset="0" stop-color="#24252E"/»«stop offset="1" stop-color="#17181F"/»«/linearGradient»
«linearGradient id="rim" x1="0" y1="0" x2="0" y2="1"»«stop offset="0" stop-color="#5A5766" stop-opacity=".9"/»«stop offset=".25" stop-color="#5A5766" stop-opacity="0"/»«/linearGradient»
«linearGradient id="bar" x1="0" y1="0" x2="0" y2="1"»«stop offset="0" stop-color="#FFF8ED"/»«stop offset=".55" stop-color="#FFE2A8"/»«stop offset="1" stop-color="#FFD17B"/»«/linearGradient»
«filter id="drop" x="-20%" y="-20%" width="140%" height="150%"»«feGaussianBlur stdDeviation="16"/»«/filter»
«filter id="bshadow" x="-50%" y="-50%" width="200%" height="200%"»«feGaussianBlur stdDeviation="7"/»«/filter»
«clipPath id="clip"»«path d="{d}"/»«/clipPath»
«/defs»
«path d="{d}" transform="translate(0 22)" fill="#000" opacity=".35" filter="url(#drop)"/»
«path d="{d}" transform="translate(0 12)" fill="#0D0E13"/»
«path d="{d}" fill="url(#face)"/»
«g clip-path="url(#clip)"»
«path d="{d}" fill="none" stroke="url(#rim)" stroke-width="6"/»
«g fill="#050507" opacity=".5" filter="url(#bshadow)"»{bars(16)}«/g»
«g fill="#B8955A"»{bars(9)}«/g»
«g fill="url(#bar)"»{bars(0)}«/g»
«g fill="none" stroke="#FFFDF6" stroke-width="2.5" opacity=".9"»{hl}«/g»
«/g»
«/svg»
'''
svg=svg.replace('«',chr(60)).replace('»',chr(62))
open('veloura-icon.svg','w').write(svg)
