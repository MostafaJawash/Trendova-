package server
import (
 "context"
 "testing"
 inventoryv1 "inventory-service/gen/inventoryv1"
 "google.golang.org/grpc/codes"
 "google.golang.org/grpc/status"
)
func TestNormalize(t *testing.T){
 tests:=[]struct{name string; in []*inventoryv1.ReserveItem; want int; bad bool}{
  {"empty",nil,0,true},{"invalid",[]*inventoryv1.ReserveItem{{ProductId:1,Quantity:0}},0,true},{"aggregate",[]*inventoryv1.ReserveItem{{ProductId:2,Quantity:1},{ProductId:1,Quantity:2},{ProductId:2,Quantity:3}},2,false},
 };for _,tt:=range tests{got,e:=normalize(tt.in);if (e!=nil)!=tt.bad||(!tt.bad&&len(got)!=tt.want){t.Fatalf("%s got=%v err=%v",tt.name,got,e)}}
}
func TestReserveValidation(t *testing.T){s:=&Server{};tests:=[]*inventoryv1.ReserveRequest{{},{ReservationId:"x"},{ReservationId:"x",Items:[]*inventoryv1.ReserveItem{{ProductId:1,Quantity:0}}}};for _,r:=range tests{_,e:=s.Reserve(context.Background(),r);if status.Code(e)!=codes.InvalidArgument{t.Fatalf("request %#v: %v",r,e)}}
}
