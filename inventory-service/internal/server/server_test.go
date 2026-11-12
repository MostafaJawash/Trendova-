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

func TestDedupeIDs(t *testing.T){
 got,e:=dedupeIDs([]int64{3,1,3,2,1});if e!=nil||len(got)!=3||got[0]!=3||got[1]!=1||got[2]!=2{t.Fatalf("got=%v err=%v",got,e)}
 if _,e=dedupeIDs([]int64{1,0});e==nil{t.Fatal("non-positive id must be rejected")}
 big:=make([]int64,MaxBatch+1);for i:=range big{big[i]=int64(i+1)};if _,e=dedupeIDs(big);e==nil{t.Fatal("batch above MaxBatch must be rejected")}
}
func TestGetStockBatchValidation(t *testing.T){
 s:=&Server{}
 r,e:=s.GetStockBatch(context.Background(),&inventoryv1.GetStockBatchRequest{});if e!=nil||len(r.GetItems())!=0{t.Fatalf("empty request must return an empty response: %v %v",r,e)}
 _,e=s.GetStockBatch(context.Background(),&inventoryv1.GetStockBatchRequest{ProductIds:[]int64{-1}});if status.Code(e)!=codes.InvalidArgument{t.Fatalf("got %v",e)}
}
