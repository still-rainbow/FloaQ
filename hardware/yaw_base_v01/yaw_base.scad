// A208 YAW-ONLY base V0.1, millimetres. No launcher or pitch mechanism.
// Purchased servo and bearing are simplified reference envelopes, NOT print parts.
part="assembly";
yaw=25;
exploded=false;
show_hardware=true;
cutaway=false;
quality=80;
qa_mode=false;
$fn=quality;
eps=0.02;
base_d=180; base_t=6;
post_xy=56; carrier_z=52; carrier_t=8; carrier_w=132;
bearing_z=carrier_z+carrier_t;
bearing_h=9; bearing_w=102; bearing_pitch=81; bearing_clear_d=50;
rotor_z=bearing_z+bearing_h;
rotor_d=160; rotor_t=8;
cradle_z=34; cradle_t=6;
servo_x0=-10.35; servo_l=40.7; servo_w=19.7;
servo_cut_x0=-10.85; servo_cut_l=41.7;
servo_mount_x=[-14.2,34.8]; servo_mount_d=3.5;
servo_body_z=13.2; servo_case_h=37;
dog_r=18; dog_w=6; dog_h=7; dog_slot_w=6.8;
driver_z=58; driver_t=4;
receiver_drop=4; receiver_slot_depth=7;
frame_bolts=[for(x=[-post_xy,post_xy],y=[-post_xy,post_xy]) [x,y]];
cradle_bolts=[for(x=[-23,45],y=[-19,19]) [x,y]];
foot_bolts=[for(a=[0:90:270]) [82*cos(a),82*sin(a)]];
assert(driver_z+driver_t+dog_h<rotor_z-receiver_drop+receiver_slot_depth,"Dog tip must not preload receiver roof");
assert(driver_z+driver_t<rotor_z-receiver_drop,"Driver must not carry tabletop weight");
assert(servo_cut_x0-(servo_mount_x[0]+servo_mount_d/2)>=1.5,"Left servo mounting web is too thin");
assert((servo_mount_x[1]-servo_mount_d/2)-(servo_cut_x0+servo_cut_l)>=1.5,"Right servo mounting web is too thin");

module hole(d,h){translate([0,0,-eps]) cylinder(d=d,h=h+2*eps);}
module rounded_plate(w,h,t,r=4){linear_extrude(t) hull() for(x=[-w/2+r,w/2-r],y=[-h/2+r,h/2-r]) translate([x,y]) circle(r=r);}
module slot2d(p1,p2,d){hull(){translate(p1) circle(d=d);translate(p2) circle(d=d);}}
module slot(p1,p2,d,h){translate([0,0,-eps]) linear_extrude(h+2*eps) slot2d(p1,p2,d);}
module hex_hole(af,h){translate([0,0,-eps]) cylinder(d=af/cos(30),h=h+eps,$fn=6);}
module bearing_bolts(){for(x=[-bearing_pitch/2,bearing_pitch/2],y=[-bearing_pitch/2,bearing_pitch/2]) translate([x,y,0]) children();}

module frame(){
 difference(){
  union(){
   cylinder(d=base_d,h=base_t);
   for(p=frame_bolts) translate([p[0],p[1],base_t]) cylinder(d=14,h=carrier_z-base_t);
   for(p=cradle_bolts) translate([p[0],p[1],base_t]) cylinder(d=11,h=cradle_z-base_t);
   // Low radial ribs stay below the servo and leave the cable exit open.
   for(p=frame_bolts) hull(){translate([p[0],p[1],base_t]) cylinder(d=12,h=4);cylinder(d=45,h=base_t+4);}
  }
  for(p=frame_bolts){translate([p[0],p[1],0]) hole(4.5,carrier_z);translate([p[0],p[1],0]) hex_hole(7.4,4);}
  for(p=cradle_bolts){translate([p[0],p[1],0]) hole(3.5,cradle_z);translate([p[0],p[1],0]) hex_hole(5.8,3.2);}
  for(p=foot_bolts) translate([p[0],p[1],0]) hole(5.5,base_t);
  if(!qa_mode) translate([-28,-72,base_t-0.45]) linear_extrude(0.5) text("YAW ONLY / V0.1",size=4,font="Liberation Sans");
 }
}

module carrier(){
 difference(){
  rounded_plate(carrier_w,carrier_w,carrier_t,14);
  hole(54,carrier_t);
  for(p=frame_bolts) translate([p[0],p[1],0]) hole(4.5,carrier_t);
  bearing_bolts() hole(4.5,carrier_t);
  // Upper bearing screws are accessible when the rotor is turned 45 degrees.
  for(a=[0:90:270]) rotate([0,0,a]) translate([bearing_pitch/sqrt(2),0,0]) hole(10,carrier_t);
  // Servo cable may exit the open side under this plate.
  if(!qa_mode) translate([-17,-62,carrier_t-0.4]) linear_extrude(0.5) text("FRONT",size=4);
 }
}

module cradle(){
 difference(){
  translate([11,0,0]) rounded_plate(78,50,cradle_t,4);
  // 0.5 mm nominal clearance around the 40.7 mm reference servo body.
  translate([servo_cut_x0,-10.85,-eps]) cube([servo_cut_l,21.7,cradle_t+2*eps]);
  for(p=cradle_bolts){
   translate([p[0],p[1],0]) hole(3.5,cradle_t);
  }
  // Round reference holes preserve printable webs beside the body opening.
  // Verify the exact servo before printing; drill only after a fit check.
  for(x=servo_mount_x,y=[-5,5]) translate([x,y,0]) hole(servo_mount_d,cradle_t);
 }
}

module rotor_native(){
 // Print inverted: broad top face on the bed, receiver boss grows upward.
 difference(){
  union(){cylinder(d=rotor_d,h=rotor_t);translate([0,0,rotor_t]) cylinder(d=48,h=receiver_drop);}
  hole(14,rotor_t+receiver_drop); // Access to factory horn's centre screw.
  bearing_bolts(){hole(4.5,rotor_t);hex_hole(7.4,4);}
  for(pitch=[60,100],x=[-pitch/2,pitch/2],y=[-pitch/2,pitch/2]){
   translate([x,y,0]) hole(4.5,rotor_t);
   translate([x,y,rotor_t-3.6]) hex_hole(7.4,3.6+eps);
  }
  for(s=[-1,1]) translate([s*dog_r-5,-dog_slot_w/2,rotor_t+receiver_drop-receiver_slot_depth]) cube([10,dog_slot_w,receiver_slot_depth+eps]);
  if(!qa_mode) translate([-11,-70,-eps]) linear_extrude(0.5) text("FRONT",size=4);
 }
}
module rotor_at(a=yaw,z=rotor_z){translate([0,0,z+rotor_t]) rotate([180,0,a]) rotor_native();}

module driver(){
 difference(){
  union(){
   cylinder(d=46,h=driver_t);
   for(s=[-1,1]) translate([s*dog_r-dog_w/2,-dog_w/2,driver_t]) cube([dog_w,dog_w,dog_h]);
  }
  hole(10,driver_t);
  // M2 fasteners to a factory horn: radial hole positions 7.5..12.5 mm.
  for(a=[0:90:270]) rotate([0,0,a]){
   slot([7.5,0],[12.5,0],2.6,driver_t);
   translate([0,0,driver_t-1.6]) slot([7.5,0],[12.5,0],4.5,1.6);
  }
 }
}
module driver_at(a=yaw,z=driver_z){translate([0,0,z]) rotate([0,0,a]) driver();}
module shim(){difference(){cylinder(d=10,h=1);hole(3.5,1);}}

module fit_coupon(){
 difference(){
  rounded_plate(66,30,6,3);
  for(i=[0:2]) translate([-22+i*22,0,0]) hole([3.5,4.5,5.5][i],6);
  translate([-22,9,2.8]) hex_hole(5.8,3.2);
  translate([0,9,2]) hex_hole(7.4,4);
  if(!qa_mode) for(i=[0:2]) translate([-22+i*22,-11,5.6]) linear_extrude(.5) text(str([3.5,4.5,5.5][i]),size=3,halign="center");
 }
}

// Simplified bought hardware, including conservative bearing central clearance.
module servo_ref(){
 color([0.14,0.17,0.20]) translate([servo_x0,-servo_w/2,servo_body_z]) cube([servo_l,servo_w,servo_case_h]);
 color([0.14,0.17,0.20]) translate([-17,-10,40]) cube([54,20,2.5]);
 color([0.72,0.57,0.27]) translate([0,0,50.2]) cylinder(d=6,h=6);
 color([0.22,0.25,0.29]) translate([0,0,55.6]) rotate([0,0,yaw]) difference(){cylinder(d=25,h=2.4);hole(4,2.4);}
}
module bearing_ref(a=yaw,z=bearing_z){
 color([0.65,0.68,0.72]) translate([0,0,z]) difference(){rounded_plate(bearing_w,bearing_w,0.75,2);hole(bearing_clear_d,0.75);bearing_bolts() hole(4.25,0.75);}
 color([0.49,0.53,0.59]) translate([0,0,z+0.75]) difference(){cylinder(d=92,h=bearing_h-1.5);hole(bearing_clear_d,bearing_h-1.5);}
 color([0.75,0.78,0.82]) translate([0,0,z+bearing_h-0.75]) rotate([0,0,a]) difference(){rounded_plate(bearing_w,bearing_w,0.75,2);hole(bearing_clear_d,0.75);bearing_bolts() hole(4.25,0.75);}
}
module fixed_parts(){frame();translate([0,0,carrier_z]) carrier();translate([0,0,cradle_z]) cradle();}
module moving_parts(){rotor_at();driver_at();}
module assembly(){
 lift=exploded?30:0;
 color([0.23,0.28,0.35]) frame();
 color([0.37,0.44,0.52]) translate([0,0,cradle_z+(exploded?12:0)]) cradle();
 color([0.66,0.71,0.77]) if(cutaway) difference(){translate([0,0,carrier_z+lift]) carrier();translate([-100,-100,40]) cube([200,100,70]);} else translate([0,0,carrier_z+lift]) carrier();
 if(show_hardware){servo_ref();bearing_ref(yaw,bearing_z+lift*2);}
 color([0.96,0.62,0.15]) driver_at(yaw,driver_z+(exploded?55:0));
 if(!cutaway) color([0.88,0.91,0.94]) rotor_at(yaw,rotor_z+lift*3);
}
// Filled envelopes conservatively contain all printed parts. The moving
// envelope is rotationally symmetric, covering all yaw angles.
module fixed_envelope(){
 // Circumscribe faceted circles so reduced QA resolution stays conservative.
 cylinder(d=base_d/cos(180/quality),h=10);
 for(p=frame_bolts) translate([p[0],p[1],0]) cylinder(d=14/cos(180/quality),h=carrier_z);
 for(p=cradle_bolts) translate([p[0],p[1],0]) cylinder(d=11/cos(180/quality),h=cradle_z);
 translate([-28,-25,cradle_z]) cube([78,50,cradle_t]);
 translate([0,0,carrier_z]) difference(){translate([-carrier_w/2,-carrier_w/2,0]) cube([carrier_w,carrier_w,carrier_t]);hole(54*cos(180/quality),carrier_t);}
}
module moving_envelope(){
 translate([0,0,rotor_z]) cylinder(d=rotor_d/cos(180/quality),h=rotor_t);
 translate([0,0,rotor_z-receiver_drop]) cylinder(d=48/cos(180/quality),h=receiver_drop);
 translate([0,0,driver_z]) cylinder(d=46/cos(180/quality),h=driver_t+dog_h);
}
module collision(){intersection(){fixed_envelope();moving_envelope();}}
module dog_collision(){intersection(){rotor_at();driver_at();}}
module bearing_collision(){intersection(){moving_parts();bearing_ref();}}
module servo_collision(){intersection(){fixed_parts();servo_ref();}}

if(part=="frame") frame();
else if(part=="carrier") carrier();
else if(part=="cradle") cradle();
else if(part=="rotor") rotor_native();
else if(part=="driver") driver();
else if(part=="shim") shim();
else if(part=="coupon") fit_coupon();
else if(part=="collision") collision();
else if(part=="dog_collision") dog_collision();
else if(part=="bearing_collision") bearing_collision();
else if(part=="servo_collision") servo_collision();
else assembly();
