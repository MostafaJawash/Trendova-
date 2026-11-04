package server
import(
 "context";"os";"sync";"testing";"fmt"
 "inventory-service/internal/store"
 inventoryv1 "inventory-service/gen/inventoryv1"
 "google.golang.org/grpc/codes"
 "google.golang.org/grpc/status"
)
func testServer(t *testing.T)*Server{t.Helper();url:=os.Getenv("TEST_DATABASE_URL");if url==""{t.Skip("TEST_DATABASE_URL is not set")};p,e:=store.Connect(context.Background(),url);if e!=nil{t.Fatal(e)};t.Cleanup(p.Close);_,e=p.Exec(context.Background(),"TRUNCATE reservation_items,reservations,inventory");if e!=nil{t.Fatal(e)};return &Server{DB:p}}
func TestIntegrationReserveSemantics(t *testing.T){s:=testServer(t);ctx:=context.Background();if _,e:=s.SetStock(ctx,&inventoryv1.SetStockRequest{ProductId:1,Quantity:1});e!=nil{t.Fatal(e)}
 var wg sync.WaitGroup;var mu sync.Mutex;success:=0;wg.Add(50);for i:=0;i<50;i++{go func(i int){defer wg.Done();r,e:=s.Reserve(ctx,&inventoryv1.ReserveRequest{ReservationId:fmt.Sprintf("race-%d",i),Items:[]*inventoryv1.ReserveItem{{ProductId:1,Quantity:1}}});if e!=nil{t.Error(e);return};if r.Success{mu.Lock();success++;mu.Unlock()}}(i)};wg.Wait();if success!=1{t.Fatalf("successes=%d want 1",success)};q,e:=s.GetQuantity(ctx,&inventoryv1.GetQuantityRequest{ProductId:1});if e!=nil||q.Available!=0{t.Fatalf("quantity=%v err=%v",q,e)}
 if _,e=s.SetStock(ctx,&inventoryv1.SetStockRequest{ProductId:2,Quantity:5});e!=nil{t.Fatal(e)};r,e:=s.Reserve(ctx,&inventoryv1.ReserveRequest{ReservationId:"atomic",Items:[]*inventoryv1.ReserveItem{{ProductId:2,Quantity:2},{ProductId:3,Quantity:1}}});if e!=nil||r.Success{t.Fatalf("atomic reserve %#v %v",r,e)};q,_=s.GetQuantity(ctx,&inventoryv1.GetQuantityRequest{ProductId:2});if q.Available!=5{t.Fatalf("atomicity quantity=%d",q.Available)}
 r,e=s.Reserve(ctx,&inventoryv1.ReserveRequest{ReservationId:"idem",Items:[]*inventoryv1.ReserveItem{{ProductId:2,Quantity:2}}});if e!=nil||!r.Success{t.Fatal(r,e)};r,e=s.Reserve(ctx,&inventoryv1.ReserveRequest{ReservationId:"idem",Items:[]*inventoryv1.ReserveItem{{ProductId:2,Quantity:2}}});if e!=nil||!r.AlreadyReserved{t.Fatal(r,e)};q,_=s.GetQuantity(ctx,&inventoryv1.GetQuantityRequest{ProductId:2});if q.Available!=3{t.Fatalf("double deduct %d",q.Available)}
 released,e:=s.Release(ctx,&inventoryv1.ReleaseRequest{ReservationId:"idem"});if e!=nil||!released.Released{t.Fatal(released,e)};released,e=s.Release(ctx,&inventoryv1.ReleaseRequest{ReservationId:"idem"});if e!=nil||released.Released{t.Fatal(released,e)};q,_=s.GetQuantity(ctx,&inventoryv1.GetQuantityRequest{ProductId:2});if q.Available!=5{t.Fatalf("release quantity=%d",q.Available)}
 if _,e=s.Reserve(ctx,&inventoryv1.ReserveRequest{ReservationId:"released",Items:[]*inventoryv1.ReserveItem{{ProductId:2,Quantity:1}}});e!=nil{t.Fatal(e)};if _,e=s.Release(ctx,&inventoryv1.ReleaseRequest{ReservationId:"released"});e!=nil{t.Fatal(e)};if _,e=s.Reserve(ctx,&inventoryv1.ReserveRequest{ReservationId:"released",Items:[]*inventoryv1.ReserveItem{{ProductId:2,Quantity:1}}});status.Code(e)!=codes.FailedPrecondition{t.Fatalf("released reservation error=%v",e)}
}
