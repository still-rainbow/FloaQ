// A208 V0.2 tabletop FIT-CHECK prototype. NOT a validated rescue device.
// Units mm. Manual and cable-servo release use the SAME body, pin and handle.
use <../spring_launcher_v01/launcher.scad>
part="assembly"; pitch=20; travel=0; automatic=false; pin_lift=0;
quality=64; show_hardware=true; qa_mode=false; $fn=quality; e=.02;
px=82; pz=12; pivot_height=85; stroke2=36; bearing_fit=19.25;
deck_x=[8,126,154]; servo_l=40.6; servo_w=19.8;
servo_left_hole=-14.2; servo_right_hole=34.8;
pin_hw_d=6; pin_clear_d=6.6;
assert(pitch>=0 && pitch<=45); assert(travel>=0 && travel<=41);
assert(pin_lift>=0 && pin_lift<=40);
module zh(d,h){translate([0,0,-e]) cylinder(d=d,h=h+2*e);}
module yy(d,h){rotate([-90,0,0]) cylinder(d=d,h=h);}
module xx(d,h){rotate([0,90,0]) cylinder(d=d,h=h);}
module xz_at(y){translate([0,y,0]) rotate([90,0,0]) children();}
module pose(){translate([px,0,pivot_height]) rotate([0,-pitch,0]) translate([-px,0,-pz]) children();}
module slot2(a,b,d,h){hull(){translate(a) zh(d,h);translate(b) zh(d,h);}}
module body2(){
 difference(){
  union(){
   plate(164,132,4,3);
   for(y=[-66,56]) translate([0,y,0]) cube([164,10,28]);
   translate([0,-56,0]) cube([11,112,28]);
   translate([154,-56,0]) cube([10,112,28]);
   translate([109,-28,4]) cube([11,56,20.4]);
   for(y=[-28.5,25.5]) translate([11,y,4]) cube([98,3,3.5]);
   for(y=[-25,16]) translate([37,y,4]) cube([5,9,20.4]);
   translate([19,-43,4]) cube([10,10,24]);
  }
  translate([-e,0,12]) xx(6.6,164+2*e);
  for(y=[-11,11]) translate([50,y,0]) zh(pin_clear_d,28);
  for(x=deck_x,y=[-61,61]){
   translate([x,y,0]) zh(3.5,28);
   translate([x,y,-e]) cylinder(d=5.8/cos(30),h=3.3,$fn=6);
  }
  for(x=[8,24]){
   translate([x,-38,0]) zh(3.5,28);
   translate([x,-38,-e]) cylinder(d=5.8/cos(30),h=3.3,$fn=6);
  }
  // 626ZZ bearings enter from inside; outer retaining shoulder 1.5 mm.
  translate([82,55.8,12]) yy(bearing_fit,8.7);
  translate([82,-64.5,12]) yy(bearing_fit,8.7);
  translate([82,-67,12]) yy(10,134);
  for(s=[-1,1],x=[69,95]) translate([x,s>0?55:-67,12]) yy(3.5,12);
  for(x=[54,110]){
   translate([x,-67,12]) yy(3.5,12);
   translate([x,-59,12]) rotate([-90,0,0]) cylinder(d=5.8/cos(30),h=3.2,$fn=6);
  }
  translate([10,0,12]) xx(14.4,1.02);
  for(y=[-18,18]) translate([109-e,y-6.15,6.85]) cube([1.1,12.3,16.3]);
 }
}
module deck2(){
 difference(){
   union(){plate(164,132,4,3);for(y=[-57,54]) translate([0,y,4]) cube([164,3,12]);for(y=[-11,11])translate([50,y,4])cylinder(d=12,h=15);}
  for(y=[-18,18]) translate([50,y-3,-e]) cube([60,6,4+2*e]);
  for(y=[-11,11]) translate([50,y,0]) zh(pin_clear_d,19);
  for(x=deck_x,y=[-61,61]){translate([x,y,0]) zh(3.5,4);translate([x,y,2]) cylinder(d=6.4,h=2+e);}
  for(x=[8,24]) translate([x,-38,0]) zh(3.5,4);
 }
}
// V0.2 slider variant: same shared envelope as V0.1, with both locking-pin
// bores enlarged for the unified 6 mm stainless-rod standard.
module slider2(){
 difference(){
  translate([0,-25,0])cube([24,50,20]);
  translate([-e,0,7.6])xx(6.6,24+2*e);
  translate([-e,0,7.6])xx(14.4,1.02);
  for(y=[-11,11])translate([6,y,0])zh(pin_clear_d,20);
  for(y=[-18,18]){
   translate([18,y,0])zh(3.5,20);
   translate([18,y,-e])cylinder(d=5.8/cos(30),h=5.2+e,$fn=6);
  }
 }
}
module slider2_at(t=travel){translate([44+t,0,4.4])slider2();}
module bearing_retainer(){difference(){union(){hull() for(x=[-13,13]) translate([x,0,0]) cylinder(d=14,h=3);translate([0,0,-2.2])cylinder(d=18.8,h=2.3);}translate([0,0,-2.3])cylinder(d=10,h=5.5);for(x=[-13,13]) translate([x,0,0]) zh(3.5,3);}}
module retainers_at(){for(s=[-1,1])scale([1,s,1])xz_at(56)translate([82,12,0])bearing_retainer();}
module moving_core(){body2();translate([0,0,28]) deck2();slider2_at(travel);pusher2_at();retainers_at();}
module base2(){
 difference(){
  union(){plate(190,180,8,5);for(x=[48,116],y=[-78,78]) translate([x-10,y-9,8]) cube([20,18,18]);}
  for(x=[48,116],y=[-78,78]){translate([x-11,y-4.3,8]) cube([22,8.6,19]);translate([x,y-10,17]) yy(4.5,20);}
  // Existing yaw rotor's 60/100 mm square patterns, centered at x=82.
  for(p=[60,100],x=[px-p/2,px+p/2],y=[-p/2,p/2]) translate([x,y,0]) zh(4.5,8);
  for(x=[18,66],y=[-86,-72]) translate([x,y,0]) zh(4.5,8);
 }
}
module cheek2(){
 difference(){
  linear_extrude(8) union(){
   translate([34,0]) square([96,18]);
   translate([69,8])square([26,69]);translate([82,77])circle(r=14);
   hull(){translate([48,14])circle(r=8);translate([82,30])circle(r=10);}
   hull(){translate([116,14])circle(r=8);translate([82,30])circle(r=10);}
  }
  translate([82,77,0]) zh(6.3,8);
  translate([81.6,77,-e]) cube([.8,30,8+2*e]);
  translate([64,85,4]) xx(3.5,36);
  translate([91,85,4]) rotate([0,90,0]) cylinder(d=5.8/cos(30),h=5,$fn=6);
  for(x=[48,116]) translate([x,9,0]) zh(4.5,8);
 }
}
module cheeks_at(){for(y=[-74,82]) translate([0,y,8]) rotate([90,0,0]) cheek2();}
module bridge_post(){difference(){cylinder(d=10,h=32);zh(3.5,32);}}
module pitch_arm(){difference(){linear_extrude(6) union(){hull()for(x=[-28,28])translate([x,0])circle(r=6);hull(){circle(r=8);translate([0,-20])circle(r=6);}}for(x=[-28,28])translate([x,0,0])zh(3.5,6);translate([0,-20,0])zh(3.5,6);}}
module horn_arm(){difference(){hull(){cylinder(d=27,h=6);translate([0,-20,0])cylinder(d=12,h=6);}zh(6,6);for(a=[0,90,180,270])rotate([0,0,a])slot2([8,0,0],[11,0,0],2.3,6);translate([0,-20,0])zh(3.5,6);}}
module link50(){difference(){hull()for(x=[0,50])translate([x,0,0])cylinder(d=11,h=4);for(x=[0,50])translate([x,0,0])zh(3.5,4);}}
module link_washer(){difference(){cylinder(d=7,h=1);zh(3.5,1);}}
module pitch_drive(){
 pose(){for(x=[54,110])translate([x,-98,12])rotate([-90,0,0])bridge_post();xz_at(-98)translate([82,12,0])pitch_arm();}
 xz_at(-98)translate([32,85,0])rotate([0,0,pitch])horn_arm();
 xz_at(-105)translate([32+20*sin(pitch),85-20*cos(pitch),0])link50();
 for(x=[32,82])xz_at(-104)translate([x+20*sin(pitch),85-20*cos(pitch),0])link_washer();
}
module mount_holes(axis_x,axis_z,y0,depth){for(x=[servo_left_hole,servo_right_hole],z=[-5,5])hull()for(dx=[-1,1])translate([axis_x+x+dx,y0,axis_z+z])yy(3.5,depth);}
module servo_reference(axis_x,axis_z,mount_y){
 // Approximate envelope, NOT an exact drawing of every MG996R clone.
 color([.14,.17,.22])translate([axis_x-10,mount_y-25.5,axis_z-servo_w/2])cube([servo_l,36.5,servo_w]);
 color([.15,.17,.22])for(x=[axis_x-18,axis_x+30.6])translate([x,mount_y-3,axis_z-9.9])cube([8,3,19.8]);
 color([.85,.86,.88])translate([axis_x,mount_y+11,axis_z])yy(6,6);
}
module pitch_mount(){
 difference(){
  union(){
   // External mount: the original full-depth floor plate crossed 08_pitch_cheek.
   // Keep the servo axis unchanged and attach entirely outside the near cheek.
   translate([8,-124,8])cube([122,31,6]);
   // Reuse the two unobstructed outer-row holes already present in 07_base.
   for(x=[18,66])translate([x-6,-93,8])cube([12,10.2,6]);
   // Bear on the outside faces of both near-side cheek sockets. Their existing
   // clamp bolts pass through this rail as two additional attachments.
   translate([34,-93,8])cube([96,6,24]);
   translate([8,-122,8])cube([68,6,94]);
   // Both ribs project outward from the cheek; no old inward-pointing gusset
   // remains to cross 08_pitch_cheek.
   for(x=[8,70])hull(){translate([x,-116,14])cube([6,6,40]);translate([x,-93,14])cube([6,6,6]);}
  }
  translate([21,-123,74])cube([42.6,8,22]);mount_holes(32,85,-123,8);
  for(x=[18,66])translate([x,-86,8-e])cylinder(d=4.5,h=8);
  for(x=[48,116])translate([x,-95,17])yy(4.5,10);
 }
}
module trigger_tower(){
 difference(){
  union(){
   translate([-12,-46,32])cube([41,16,6]);translate([-12,-30,32])cube([12,6,92]);
   translate([-12,-30,42])cube([68,6,7]);translate([50,-30,42])cube([6,6,82]);translate([-12,-30,118])cube([68,6,6]);
   translate([37,-24,104])cube([19,7,13]);
   for(z=[51,116])translate([-12,-36,z])cube([9,12,8]);
  }
  for(x=[8,24])translate([x,-38,31])cylinder(d=3.5,h=9);
  translate([43,-25,110])yy(3.5,10);
  for(z=[55,120])translate([-7.5,-37,z])yy(3.5,15);
 }
}
module trigger_adapter(){
 difference(){
  union(){translate([-12,-40,86])cube([68,4,39]);translate([-12,-40,51])cube([9,4,37]);}
  translate([1,-41,89.9])cube([42.6,6,22.2]);mount_holes(12,101,-41,6);
  for(z=[55,120])translate([-7.5,-41,z])yy(3.5,6);
 }
}
module spool(){difference(){union(){cylinder(d1=26,d2=36,h=8);translate([0,0,8])cylinder(d=36,h=1.5);translate([0,0,8])cylinder(d=32,h=6.5);translate([0,0,14.5])cylinder(d=36,h=1.5);}zh(6,16);for(a=[0,90,180,270])rotate([0,0,a])slot2([8,0,0],[11,0,0],2.3,16);translate([14,0,8])zh(2,8);}}
module pulley(){difference(){union(){cylinder(d=18,h=1.5);cylinder(d=14,h=5.5);translate([0,0,5.5])cylinder(d=18,h=1.5);}zh(5.5,7);translate([0,0,1.5])cylinder(d=10.2,h=5.6);}}
module pulley_spacer(){difference(){cylinder(d=5.2,h=4);zh(3.3,4);}}
module pull_handle(){difference(){hull()for(x=[-8,8])translate([x,0,0])cylinder(d=18,h=4);zh(pin_clear_d,4);for(x=[-10,10])translate([x,0,0])zh(2.2,4);}}
module pusher2(){
 difference(){
  pusher_native();
  for(y=[-40,40]){translate([0,y,0])zh(3.5,7);translate([0,y,4])cylinder(d=5.8/cos(30),h=3.1,$fn=6);}
 }
}
module cocking_grip(){
 // Flat printable side profile. Assembly profile x->Y, y->Z, extrusion->X.
 difference(){
  linear_extrude(10)union(){translate([-6,0])square([16,5]);translate([4,0])square([6,14.6]);translate([4,8.6])square([30,6]);}
  translate([0,-e,5])yy(3.5,5+2*e);
 }
}
module grips_at(){
 for(s=[-1,1])scale([1,s,1])translate([62+travel,40,39.4])multmatrix([[0,0,1,-5],[1,0,0,0],[0,1,0,0],[0,0,0,1]])cocking_grip();
}
module pusher2_at(){translate([62+travel,0,39.4])rotate([180,0,0])pusher2();grips_at();}
module pin_parts(safety=false){
 y=safety?11:-11; lift=safety?0:pin_lift;
 color(safety?[.94,.28,.15]:[.96,.65,.14])translate([50,y,47+lift])pull_handle();
  if(show_hardware){color([.65,.67,.7])translate([50,y,-1+lift])cylinder(d=pin_hw_d,h=60);color([.3,.34,.38])translate([50,y,51+lift])difference(){cylinder(d=15,h=6);zh(pin_hw_d,6);}}
}
module cord_reference(){
 // Routing diagram, not a simulated flexible cable. Tune the bridle on the bench.
 pts=[[50,-11,61+pin_lift],[50,-11,110],[48,-11,115],[43,-11,117],[12,-11,117]];
 for(i=[0:len(pts)-2])hull(){translate(pts[i])sphere(d=.7);translate(pts[i+1])sphere(d=.7);}
}
module auto_parts(){
 trigger_adapter();translate([12,-23,101])rotate([-90,0,0])spool();
 translate([43,-14.5,110])rotate([-90,0,0])pulley();translate([43,-17,110])rotate([-90,0,0])pulley_spacer();
 if(show_hardware){servo_reference(12,101,-40);color([.95,.62,.12])cord_reference();}
}
module trigger_all(){color([.19,.27,.34])trigger_tower();pin_parts();pin_parts(true);if(automatic)color([.2,.56,.63])auto_parts();}
module references(){
 color([.65,.67,.7])translate([-8,0,12])xx(6,160);
 for(y=[-18,18])color([.15,.15,.15])translate([104,y-6,7])cube([6,12,16]);
 color([.2,.6,.9,.3])translate([12,0,12])rotate([0,90,0])difference(){cylinder(d=14,h=32+travel);zh(8,32+travel);}
 for(y=[58.5,-64.5])color([.64,.66,.69])translate([82,y,12])rotate([-90,0,0])difference(){cylinder(d=19,h=6);zh(6,6);}
}
module shaft_references(){for(y=[45,-90])color([.64,.66,.69])translate([82,y,85])yy(6,45);for(y=[45,83,-51,-89])color([.4,.43,.46])translate([82,y,85])rotate([-90,0,0])difference(){cylinder(d=15,h=6);zh(6,6);}}
module assembly2(){
 color([.82,.86,.88])base2();color([.21,.29,.36]){cheeks_at();pitch_mount();}color([.16,.56,.64])pitch_drive();
 if(show_hardware){servo_reference(32,85,-122);shaft_references();}
 pose(){color([.84,.87,.89])body2();color([.29,.34,.39])translate([0,0,28])deck2();color([.2,.25,.3])slider2_at(travel);color([.96,.66,.17])pusher2_at();color([.8,.83,.85])retainers_at();color([1,.33,.07])buoy_at(travel);trigger_all();if(show_hardware)references();}
}
module coupon2(){difference(){plate(130,42,9,2);for(i=[0:2])translate([16+i*30,0,0])zh([19.1,19.25,19.4][i],9);translate([109,8,0])zh(6.4,9);translate([120,8,0])zh(6.6,9);if(!qa_mode){for(i=[0:2])translate([7+i*30,-18,8.6])linear_extrude(.5)text(str([19.1,19.25,19.4][i]),size=3);translate([106,15,8.6])linear_extrude(.5)text("6.4",size=3);translate([117,15,8.6])linear_extrude(.5)text("6.6",size=3);}}}
module qa_drive(){intersection(){union(){body2();translate([0,0,28])deck2();}union(){slider2_at(travel);pusher2_at();}}}
module cassette_envelope(){
 // Conservative closed envelopes: core, rear tower including servo, pin, tool.
 translate([0,-66,0])cube([167+travel,132,48]);
 translate([-12,-66,32])cube([68,132,93]);
 translate([48,-17,-1])cube([4,34,101]);
 translate([57+travel,-74,39.4])cube([10,148,14.6]);
}
module qa_stand(){intersection(){pose()cassette_envelope();union(){base2();cheeks_at();pitch_mount();}}}
module qa_bridge(){intersection(){pitch_drive();union(){cheeks_at();base2();pitch_mount();}}}
// Offset only the QA copy by 0.05 mm away from the two intentional mating
// planes. This prevents zero-thickness coplanar contact from being exported as
// a false collision while still detecting any physical interpenetration.
module qa_mount(){intersection(){translate([0,-.05,.05])pitch_mount();union(){base2();cheeks_at();}}}
module qa_trigger(){intersection(){union(){trigger_tower();if(automatic)auto_parts();}union(){pusher2_at();buoy_at(travel);}}}
module qa_pin(){intersection(){translate([50,-11,-1+pin_lift])cylinder(d=pin_hw_d,h=60);slider2_at(travel);}}
if(part=="body")body2();else if(part=="deck")deck2();else if(part=="slider")slider2();
else if(part=="pusher")translate([5,46,0])pusher2();else if(part=="buoy")buoy();else if(part=="grip")translate([6,0,0])cocking_grip();
else if(part=="base")base2();else if(part=="cheek")cheek2();else if(part=="retainer")translate([20,9.4,3])rotate([180,0,0])bearing_retainer();else if(part=="post")bridge_post();
else if(part=="pitch_arm")translate([34,26,0])pitch_arm();else if(part=="horn_arm")translate([14,26,0])horn_arm();else if(part=="link")translate([6,6,0])link50();else if(part=="link_washer")link_washer();
else if(part=="pitch_mount")translate([-8,102,124])rotate([90,0,0])pitch_mount();
else if(part=="tower")translate([12,124,46])rotate([90,0,0])trigger_tower();
else if(part=="adapter")translate([12,125,40])rotate([90,0,0])trigger_adapter();
else if(part=="spool")spool();else if(part=="pulley")pulley();else if(part=="pulley_spacer")pulley_spacer();else if(part=="handle")translate([16,8,0])pull_handle();else if(part=="coupon")coupon2();
else if(part=="trigger_detail"){trigger_all();color([.85,.88,.9])body2();color([.3,.36,.4])translate([0,0,28])deck2();}
 else if(part=="qa_drive")qa_drive();else if(part=="qa_stand")qa_stand();else if(part=="qa_bridge")qa_bridge();else if(part=="qa_mount")qa_mount();else if(part=="qa_trigger")qa_trigger();else if(part=="qa_pin")qa_pin();else assembly2();
