/* Orthographic, CPU canvas viewer. Geometry only, no synthetic ray paths. */
class LensGeometryViewer {
  constructor(canvas){
    this.canvas=canvas;this.ctx=canvas.getContext("2d");this.model=null;this.mesh=[];this.points=[];
    this.yaw=-0.45;this.pitch=0.24;this.zoom=1;this.drag=null;this.pending=false;
    canvas.tabIndex=0;
    canvas.addEventListener("pointerdown",e=>{this.drag={x:e.clientX,y:e.clientY};canvas.setPointerCapture(e.pointerId);});
    canvas.addEventListener("pointermove",e=>{if(!this.drag)return;this.yaw+=(e.clientX-this.drag.x)*.006;this.pitch=Math.max(-1.35,Math.min(1.35,this.pitch+(e.clientY-this.drag.y)*.006));this.drag={x:e.clientX,y:e.clientY};this.draw();});
    const release=()=>{this.drag=null;};canvas.addEventListener("pointerup",release);canvas.addEventListener("pointercancel",release);
    canvas.addEventListener("wheel",e=>{e.preventDefault();this.zoom=Math.max(.25,Math.min(8,this.zoom*Math.exp(-e.deltaY*.001)));this.draw();},{passive:false});
    canvas.addEventListener("dblclick",()=>this.reset());
    canvas.addEventListener("keydown",e=>{let handled=true;
      if(e.key==="ArrowLeft")this.yaw-=.08;else if(e.key==="ArrowRight")this.yaw+=.08;
      else if(e.key==="ArrowUp")this.pitch=Math.max(-1.35,this.pitch-.08);else if(e.key==="ArrowDown")this.pitch=Math.min(1.35,this.pitch+.08);
      else if(e.key==="+"||e.key==="=")this.zoom=Math.min(8,this.zoom*1.15);else if(e.key==="-")this.zoom=Math.max(.25,this.zoom/1.15);
      else if(e.key.toLowerCase()==="r")this.reset();else handled=false;
      if(handled){e.preventDefault();this.draw();}
    });
    this.resizeObserver=new ResizeObserver(()=>this.draw());this.resizeObserver.observe(canvas.parentElement);
  }
  reset(){this.yaw=-.45;this.pitch=.24;this.zoom=1;this.draw();}
  side(){this.yaw=0;this.pitch=0;this.zoom=1;this.draw();}
  rotate(p){const cy=Math.cos(this.yaw),sy=Math.sin(this.yaw),cp=Math.cos(this.pitch),sp=Math.sin(this.pitch);const x=cy*p[0]+sy*p[2],z=-sy*p[0]+cy*p[2];return[x,cp*p[1]-sp*z,sp*p[1]+cp*z];}
  setModel(model){
    this.model=model;this.mesh=[];this.points=[];this.center=0;
    if(!model||!model.surfaces.length){this.draw();return;}
    const allZ=model.surfaces.map(s=>s.z);allZ.push(model.sensor_z);this.center=(Math.min(...allZ)+Math.max(...allZ))/2;
    this.maxRadius=Math.max(model.sensor_radius,...model.surfaces.map(s=>s.radius));
    const palette=[[62,133,202],[67,151,153],[128,112,189],[78,137,194],[55,152,130]];
    const point=(s,j,a)=>{const p=s.profile[j];if(!p||p[1]===null)return null;return[s.z+p[1]-this.center,p[0]*Math.cos(a),p[0]*Math.sin(a)];};
    const add=(points,color,alpha=.13,edge=false)=>{if(points.some(p=>!p||p.some(v=>!Number.isFinite(v))))return;this.mesh.push({points,color,alpha,edge});this.points.push(...points);};
    let glassIndex=-1;
    for(let i=0;i<model.surfaces.length;i++){
      const s=model.surfaces[i];if(s.type==="Aperture")continue;
      if(s.material.toLowerCase()!=="air")glassIndex++;
      const color=palette[Math.max(glassIndex,0)%palette.length];
      const steps=[];for(let j=0;j<s.profile.length;j+=4)steps.push(j);if(steps[steps.length-1]!==s.profile.length-1)steps.push(s.profile.length-1);
      for(let k=1;k<steps.length;k++)for(let a=0;a<40;a++){
        const t=a*2*Math.PI/40,u=(a+1)*2*Math.PI/40;
        add([point(s,steps[k-1],t),point(s,steps[k],t),point(s,steps[k],u),point(s,steps[k-1],u)],color,.10);
      }
      const next=model.surfaces[i+1];
      if(s.material.toLowerCase()!=="air"&&next&&next.type!=="Aperture")for(let a=0;a<40;a++){
        const t=a*2*Math.PI/40,u=(a+1)*2*Math.PI/40;
        add([point(s,s.profile.length-1,t),point(next,next.profile.length-1,t),point(next,next.profile.length-1,u),point(s,s.profile.length-1,u)],color,.20,true);
      }
    }
    // STOP ring and image plane are schematic markers, not mount geometry.
    for(const s of model.surfaces.filter(s=>s.type==="Aperture"))for(let a=0;a<64;a++){
      const t=a*2*Math.PI/64,u=(a+1)*2*Math.PI/64,z=s.z-this.center;
      const p=(r,t)=>[z,r*Math.cos(t),r*Math.sin(t)];
      add([p(s.radius,t),p(s.radius*1.13,t),p(s.radius*1.13,u),p(s.radius,u)],[227,179,108],.36,true);
    }
    const h=model.sensor_radius/Math.sqrt(2),z=model.sensor_z-this.center;
    add([[z,-h,-h],[z,h,-h],[z,h,h],[z,-h,h]],[174,153,224],.12,true);
    this.draw();
  }
  draw(){if(this.pending)return;this.pending=true;requestAnimationFrame(()=>{this.pending=false;this.render();});}
  render(){
    const canvas=this.canvas,rect=canvas.getBoundingClientRect(),w=Math.round(rect.width),h=Math.round(rect.height);if(!w||!h)return;
    const dpr=Math.min(window.devicePixelRatio||1,2);if(canvas.width!==Math.round(w*dpr)||canvas.height!==Math.round(h*dpr)){canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr);}
    const ctx=this.ctx;ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);
    if(!this.model||!this.points.length)return;
    const rotated=this.points.map(p=>this.rotate(p));const xs=rotated.map(p=>p[0]),ys=rotated.map(p=>p[1]);
    let xmin=Math.min(...xs),xmax=Math.max(...xs),ymin=Math.min(...ys),ymax=Math.max(...ys);
    const scale=Math.min((w-100)/Math.max(xmax-xmin,1),(h-95)/Math.max(ymax-ymin,1))*this.zoom;
    const ox=w/2-(xmin+xmax)/2*scale,oy=h/2+(ymin+ymax)/2*scale;
    const project=p=>{const q=this.rotate(p);return[ox+q[0]*scale,oy-q[1]*scale,q[2]];};
    const line=(points,color,width=1,dash=[])=>{ctx.strokeStyle=color;ctx.lineWidth=width;ctx.setLineDash(dash);ctx.beginPath();points.forEach((p,i)=>{const q=project(p);i?ctx.lineTo(q[0],q[1]):ctx.moveTo(q[0],q[1]);});ctx.stroke();ctx.setLineDash([]);};
    const start=this.model.surfaces[0].z-this.center,finish=this.model.sensor_z-this.center,r=this.maxRadius;
    // A faint construction grid helps rotation; it is not part of the lens.
    for(let i=0;i<=8;i++){const x=start+(finish-start)*i/8;line([[x,-r*1.12,-r],[x,-r*1.12,r]],"#92acd00c");}
    for(let i=0;i<=4;i++){const z=-r+r*i/2;line([[start,-r*1.12,z],[finish,-r*1.12,z]],"#92acd00c");}
    line([[start-r*.5,0,0],[finish+r*.4,0,0]],"#7d9fc45c",1,[4,4]);
    const mesh=this.mesh.map(face=>{const pts=face.points.map(project);return{...face,pts,depth:pts.reduce((sum,p)=>sum+p[2],0)/pts.length};}).sort((a,b)=>a.depth-b.depth);
    const wire=$("wire3d").checked;
    for(const f of mesh){ctx.beginPath();f.pts.forEach((p,i)=>i?ctx.lineTo(p[0],p[1]):ctx.moveTo(p[0],p[1]));ctx.closePath();ctx.fillStyle=`rgba(${f.color.join(",")},${f.alpha})`;ctx.fill();if(wire||f.edge){ctx.strokeStyle=`rgba(${f.color.join(",")},${f.edge ? .28 : .10})`;ctx.lineWidth=.65;ctx.stroke();}}
    // Precise meridian profiles keep very thin and nearly flat lenses legible.
    for(const s of this.model.surfaces){if(s.type==="Aperture")continue;for(const a of [0,Math.PI]){const pts=s.profile.filter(p=>p[1]!==null).map(p=>[s.z+p[1]-this.center,p[0]*Math.cos(a),p[0]*Math.sin(a)]);line(pts,"#a4cdeb99",.9);}}
    ctx.font='10px "Segoe UI",sans-serif';ctx.fillStyle="#566f8d";
    const label=(text,p,color)=>{const q=project(p);ctx.fillStyle=color;ctx.fillText(text,q[0]+6,q[1]-6);};
    for(const s of this.model.surfaces.filter(s=>s.type==="Aperture"))label("STOP",[s.z-this.center,s.radius*1.16,0],"#9c6b1f");
    label("IMAGE",[finish,this.model.sensor_radius/Math.sqrt(2),0],"#7b60ac");
    const length=Math.pow(10,Math.floor(Math.log10(Math.max(1,(xmax-xmin)/4))));
    ctx.strokeStyle="#7898bd";ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(20,h-45);ctx.lineTo(20+length*scale,h-45);ctx.stroke();ctx.fillStyle="#7695b9";ctx.fillText(length+" mm",20,h-52);
  }
}
const lensViewer=new LensGeometryViewer($("lens3d"));
$("reset3d").onclick=()=>lensViewer.reset();$("viewIso").onclick=()=>lensViewer.reset();$("viewSide").onclick=()=>lensViewer.side();$("wire3d").onchange=()=>lensViewer.draw();
