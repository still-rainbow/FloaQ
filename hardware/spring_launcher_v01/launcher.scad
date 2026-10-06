// A208 tabletop demonstrator V0.1 -- millimetres.
// FIT-CHECK PROTOTYPE, NOT a validated launch/rescue device.
// Spring dimensions reserve SPACE ONLY. No spring rate/product is specified.
part="assembly";
pitch=20;
travel=0; // 0=pinned; 56=nominal stop; 61=hard-stop limit
show_hardware=true;
show_projectile=true;
show_tool=false;
cutaway=false;
quality=80;
qa_mode=false; // QA may omit decorative engraving; functional geometry is unchanged.
$fn=quality;
eps=0.02;
L=164; W=132; body_h=28; floor_t=4; deck_t=4; deck_z=28;
rod_d=6; rod_clear=6.6; rod_z=12;
slider_l=24; slider_w=50; slider_h=20; slider_z=4.4;
loaded_rear=44; stroke=56; slider_cx=62;
pin_d=4.5; pin_x=50; pin_ys=[-11,11];
web_y=18; web_w=5.2; web_l=10; slot_w=6;
bar_w=92; bar_l=10; bar_h=7; bar_z=32.4;
spring_seat=12; spring_reserved_od=14;
spring_reserved_free=88; spring_reserved_min=32;
pivot_x=20; pivot_z=12; index_r=120;
index_angles=[0,10,20,30,45];
stand_pivot_z=36; stand_base_t=8;
cheek_t=8; cheek_inner_y=72; spacer_t=6;
base_l=190; base_w=180;
cocking_reach=80;
nut_m3_af=5.8; // M3 nut nominal AF 5.5; retain anti-rotation flats.
deck_bolts_x=[8,78,154]; deck_bolts_y=[-61,61];
assert(travel>=0 && travel<=stroke+5,"Travel outside CAD envelope");
assert(pitch>=0 && pitch<=45,"Pitch outside CAD sweep");
assert(spring_reserved_min==loaded_rear-spring_seat);
assert(spring_reserved_free==loaded_rear+stroke-spring_seat);

module cyl_x(d,h){rotate([0,90,0]) cylinder(d=d,h=h);}
module cyl_y(d,h){rotate([-90,0,0]) cylinder(d=d,h=h);}
module hex_y(af,h){rotate([-90,0,0]) cylinder(d=af/cos(30),h=h,$fn=6);}
module rounded_rect(size,r=2){hull() for(x=[r,size[0]-r],y=[r,size[1]-r]) translate([x,y]) circle(r=r);}
module plate(l,w,h,r=2){translate([0,-w/2,0]) linear_extrude(h) rounded_rect([l,w],r);}
module z_hole(d,h){translate([0,0,-eps]) cylinder(d=d,h=h+2*eps);}
module cassette_pose(a=pitch){translate([pivot_x,0,stand_pivot_z]) rotate([0,-a,0]) translate([-pivot_x,0,-pivot_z]) children();}

module body(){
 difference(){
  union(){
   plate(L,W,floor_t,3);
   for(s=[-1,1]) translate([0,s>0?56:-66,0]) cube([L,10,body_h]);
   translate([0,-56,0]) cube([11,112,body_h]);
   translate([154,-56,0]) cube([10,112,body_h]);
   // Front rod support and independent hard stop.
   translate([129,-28,4]) cube([11,56,20.4]);
   for(s=[-1,1]) translate([11,s>0?25.5:-28.5,4]) cube([118,3,3.5]);
   // Rear stop: at most 2 mm extra motion for pin alignment.
   for(s=[-1,1]) translate([37,s>0?16:-25,4]) cube([5,9,20.4]);
  }
  translate([-eps,0,rod_z]) cyl_x(rod_clear,L+2*eps);
  for(y=pin_ys) translate([pin_x,y,0]) z_hole(pin_d,body_h);
  for(x=deck_bolts_x,y=deck_bolts_y){
   translate([x,y,0]) z_hole(3.5,body_h);
   translate([x,y,-eps]) cylinder(d=nut_m3_af/cos(30),h=3.2+eps,$fn=6);
  }
  // Independent stub bolts each side: no full axle across the drive rod.
  for(x=[pivot_x,pivot_x+index_r]){
   d=x==pivot_x?6.6:5.5; af=x==pivot_x?10.4:8.4;
   for(y=[-66-eps,55.8]) translate([x,y,pivot_z]) cyl_y(d,10.3);
   translate([x,55.8,pivot_z]) hex_y(af,5.3);
   translate([x,-61.1,pivot_z]) hex_y(af,5.3);
  }
  translate([10,0,rod_z]) cyl_x(14.4,1.02);
  for(y=[-18,18]) translate([129-eps,y-6.15,6.85]) cube([1.1,12.3,16.3]);
 }
}
module deck(){
 difference(){
  union(){
   plate(L,W,deck_t,3);
   for(s=[-1,1]) translate([0,s>0?54:-57,deck_t]) cube([L,3,12]);
  }
  for(y=[-web_y,web_y]) translate([50,y-slot_w/2,-eps]) cube([80,slot_w,deck_t+2*eps]);
  for(y=pin_ys) translate([pin_x,y,0]) z_hole(pin_d,deck_t);
  for(x=deck_bolts_x,y=deck_bolts_y){
   translate([x,y,0]) z_hole(3.5,deck_t);
   translate([x,y,deck_t-2]) cylinder(d=6.4,h=2+eps);
  }
  if(!qa_mode) translate([9,-45,deck_t-0.45]) linear_extrude(0.5) text("FIT V0.1",size=4,font="Liberation Sans:style=Bold");
 }
}
// Export coordinates: carriage rear x=0, bottom z=0.
module slider(){
 difference(){
  translate([0,-slider_w/2,0]) cube([slider_l,slider_w,slider_h]);
  translate([-eps,0,rod_z-slider_z]) cyl_x(rod_clear,slider_l+2*eps);
  translate([-eps,0,rod_z-slider_z]) cyl_x(14.4,1.02);
  for(y=pin_ys) translate([pin_x-loaded_rear,y,0]) z_hole(pin_d,slider_h);
  for(y=[-web_y,web_y]){
   translate([slider_cx-loaded_rear,y,0]) z_hole(3.5,slider_h);
   translate([slider_cx-loaded_rear,y,-eps]) cylinder(d=nut_m3_af/cos(30),h=5.2+eps,$fn=6);
  }
 }
}
// Print inverted: bar on bed, webs grow upward, no supports.
module pusher_native(){
 difference(){
  union(){
   translate([-bar_l/2,-bar_w/2,0]) cube([bar_l,bar_w,bar_h]);
   for(y=[-web_y,web_y]) translate([-web_l/2,y-web_w/2,bar_h]) cube([web_l,web_w,bar_z-slider_z-slider_h]);
  }
  for(y=[-web_y,web_y]){
   translate([0,y,0]) z_hole(3.5,30);
   translate([0,y,-eps]) cylinder(d=6.4,h=3+eps);
  }
 }
}
module pusher_at(t=travel){translate([slider_cx+t,0,bar_z+bar_h]) rotate([180,0,0]) pusher_native();}
module slider_at(t=travel){translate([loaded_rear+t,0,slider_z]) slider();}
module deck_at(){translate([0,0,deck_z]) deck();}

module base(){
 difference(){
  union(){
   plate(base_l,base_w,stand_base_t,5);
   for(x=[42,144],s=[-1,1]) translate([x-10,s*76-9,8]) cube([20,18,20]);
  }
  for(x=[42,144],s=[-1,1]){
   translate([x-11,s*76-4.25,8]) cube([22,8.5,20+eps]);
   translate([x,s*76-10,17]) cyl_y(4.5,20);
  }
  for(x=[12,178],y=[-51,51]) translate([x,y,0]) z_hole(6.5,stand_base_t);
  if(!qa_mode) translate([55,-75,7.5]) linear_extrude(0.6) text("SPRING DEMO / V0.1",size=4.2,font="Liberation Sans:style=Bold");
 }
}
// Export cheek flat in XY; source y becomes world z in assembly.
module cheek_profile(){
 py=stand_pivot_z-stand_base_t;
 union(){
  rounded_rect([164,16],3);
  translate([pivot_x,py]) circle(r=13);
  hull(){translate([20,8]) circle(r=8);translate([pivot_x,py]) circle(r=8);}
  hull(){translate([pivot_x,py]) circle(r=7);translate([148,15]) circle(r=7);}
  hull(){translate([pivot_x,py]) circle(r=8);translate([pivot_x+120*cos(45),py+120*sin(45)]) circle(r=9);}
  translate([132,10]) rounded_rect([24,25],3);
  polygon(concat([for(a=[0:2:50]) [pivot_x+133*cos(a),py+133*sin(a)]],
                 [for(a=[50:-2:0]) [pivot_x+108*cos(a),py+108*sin(a)]]));
 }
}
module cheek(){
 difference(){
  linear_extrude(cheek_t) cheek_profile();
  for(x=[42,144]) translate([x,9,0]) z_hole(4.5,cheek_t);
  translate([pivot_x,stand_pivot_z-stand_base_t,0]) z_hole(6.6,cheek_t);
  for(a=index_angles) translate([pivot_x+index_r*cos(a),stand_pivot_z-stand_base_t+index_r*sin(a),0]) z_hole(5.5,cheek_t);
  if(!qa_mode) for(a=index_angles) translate([pivot_x+(index_r-7)*cos(a),stand_pivot_z-stand_base_t+(index_r-7)*sin(a),cheek_t-0.5])
   linear_extrude(0.6) text(str(a),size=3.5,halign="center",valign="center",font="Liberation Sans");
 }
}
module cheek_at(s=1){translate([0,s>0?cheek_inner_y+cheek_t:-cheek_inner_y,stand_base_t]) rotate([90,0,0]) cheek();}
module spacer(){difference(){cylinder(d=14,h=spacer_t);translate([0,0,-eps]) cylinder(d=6.6,h=spacer_t+2*eps);}}
module spacer_at(x,s){translate([x,s>0?W/2:-W/2-spacer_t,pivot_z]) rotate([-90,0,0]) spacer();}

// Solid outer envelope. The slicer supplies low-density infill, not 100% solid.
module buoy(){rotate_extrude($fn=max(quality,128)) polygon([[25.8,0],[49.2,0],[50,0.8],[50,9.2],[49.2,10],[25.8,10],[25,9.2],[25,0.8]]);}
module buoy_at(t=travel){translate([slider_cx+t+bar_l/2+50,0,deck_z+deck_t]) buoy();}

// Removable cocking fork. Install BOTH steel pins, unload tool, remove it.
module cocking_fork(){
 difference(){
  union(){
   translate([-cocking_reach,-8,0]) cube([cocking_reach-14,16,6]);
   translate([-20,-51,0]) cube([6,102,6]);
   for(s=[-1,1]){
    translate([-20,s>0?47:-51,0]) cube([30,4,6]);
    translate([6,s>0?42:-51,0]) cube([4,9,6]);
   }
  }
  translate([-cocking_reach+10,0,-eps]) cylinder(d=9,h=6+2*eps);
  if(!qa_mode) translate([-cocking_reach+22,-3,5.5]) linear_extrude(0.6) text("REMOVE",size=4);
 }
}
module fit_coupon(){
 difference(){
  plate(90,32,12,2);
  for(i=[0:3]) translate([12+i*20,0,0]) z_hole([4.3,4.5,6.4,6.6][i],12);
  for(i=[0:3]) translate([12+i*20,-12,11.5]) linear_extrude(0.6) text(str([4.3,4.5,6.4,6.6][i]),size=3,halign="center");
 }
}
module slot_coupon(){difference(){plate(40,36,4,2);for(i=[0:2]) translate([5,-12+i*12-([5.6,6.0,6.4][i]/2),-eps]) cube([30,[5.6,6.0,6.4][i],4+2*eps]);}}

module hardware(){
 color([0.62,0.64,0.67]) translate([-8,0,rod_z]) cyl_x(rod_d,160);
 // Blue hollow cylinder is ONLY the space reserved for a spring, not printable.
 color([0.2,0.55,0.9,0.35]) translate([spring_seat,0,rod_z]) rotate([0,90,0]) difference(){
  cylinder(d=spring_reserved_od,h=loaded_rear+travel-spring_seat);
  translate([0,0,-eps]) cylinder(d=8,h=loaded_rear+travel-spring_seat+2*eps);
 }
 for(x=[-7,140]) color([0.4,0.42,0.45]) translate([x,0,rod_z]) rotate([0,90,0]) difference(){cylinder(d=12,h=7);translate([0,0,-eps]) cylinder(d=6,h=7+2*eps);}
 for(y=[-18,18]) color([0.18,0.18,0.18]) translate([124,y-6,7]) cube([6,12,16]);
 if(travel==0) for(i=[0,1]) color(i==0?[0.65,0.65,0.67]:[0.9,0.5,0.12]) translate([pin_x,pin_ys[i],-8]){
  cylinder(d=4,h=40);translate([0,0,40]) cylinder(d=8,h=3);
 }
 // Simplified purchased stub bolts and washers, not printable parts.
 for(x=[pivot_x,pivot_x+index_r],s=[-1,1]) color([0.57,0.59,0.63]){
  d=x==pivot_x?6:5;
  translate([x,s>0?52:-84,pivot_z]) cyl_y(d,32);
  translate([x,s>0?82:-86,pivot_z]) hex_y(x==pivot_x?10:8,4);
 }
}
module cassette(t=travel){
 color([0.86,0.88,0.90]) if(cutaway) difference(){body();translate([0,-70,8]) cube([L+1,70,60]);} else body();
 color([0.32,0.35,0.40]) if(!cutaway) deck_at();
 color([0.17,0.23,0.30]) slider_at(t);
 color([0.95,0.60,0.18]) pusher_at(t);
 if(show_projectile) color([1,0.32,0.04]) buoy_at(t);
 if(show_hardware) hardware();
 if(show_tool) color([0.16,0.52,0.7]) translate([slider_cx+t,0,bar_z+2]) cocking_fork();
}
module assembly(){
 color([0.84,0.87,0.90]) base();
 color([0.28,0.34,0.41]) for(s=[-1,1]) cheek_at(s);
 cassette_pose(){
  cassette();
  color([0.85,0.85,0.85]) for(x=[pivot_x,pivot_x+index_r],s=[-1,1]) spacer_at(x,s);
 }
}
module print_layout(){body();translate([0,160,0]) deck();translate([185,0,0]) base();translate([195,105,0]) cheek();translate([220,290,0]) buoy();translate([100,290,0]) pusher_native();translate([50,280,0]) slider();}

// Boolean QA: expected EMPTY for every tested state.
module collision_static_moving(){intersection(){union(){body();deck_at();}union(){slider_at();pusher_at();}}}
module collision_stand(){intersection(){cassette_pose() union(){body();deck_at();slider_at();pusher_at();}union(){base();cheek_at(1);cheek_at(-1);}}}
module collision_buoy(){intersection(){buoy_at();union(){body();deck_at();slider_at();pusher_at();}}}
module collision_tool(){intersection(){translate([slider_cx+travel,0,bar_z+2]) cocking_fork();union(){body();deck_at();slider_at();pusher_at();}}}

if(part=="body") body();
else if(part=="deck") deck();
else if(part=="slider") slider();
else if(part=="pusher") translate([bar_l/2,bar_w/2,0]) pusher_native();
else if(part=="base") base();
else if(part=="cheek") cheek();
else if(part=="spacer") spacer();
else if(part=="buoy") buoy();
else if(part=="cocking_fork") translate([cocking_reach,51,0]) cocking_fork();
else if(part=="fit_coupon") fit_coupon();
else if(part=="slot_coupon") slot_coupon();
else if(part=="cassette") cassette();
else if(part=="layout") print_layout();
else if(part=="collision_static_moving") collision_static_moving();
else if(part=="collision_stand") collision_stand();
else if(part=="collision_buoy") collision_buoy();
else if(part=="collision_tool") collision_tool();
else assembly();
