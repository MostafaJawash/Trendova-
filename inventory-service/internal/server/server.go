package server
import (
 "context"
 "fmt"
 "sort"
 "time"
 "github.com/jackc/pgx/v5"
 "github.com/jackc/pgx/v5/pgxpool"
 inventoryv1 "inventory-service/gen/inventoryv1"
 "google.golang.org/grpc/codes"
 "google.golang.org/grpc/status"
)
type Server struct { inventoryv1.UnimplementedInventoryServiceServer; DB *pgxpool.Pool }
type item struct{ id int64; qty int32 }
func normalize(in []*inventoryv1.ReserveItem)([]item,error){
 if len(in)==0{return nil,fmt.Errorf("items is empty")};m:=map[int64]int32{}
 for _,x:=range in {if x.GetProductId()<=0||x.GetQuantity()<=0{return nil,fmt.Errorf("product_id and quantity must be positive")};m[x.GetProductId()]+=x.GetQuantity()}
 out:=make([]item,0,len(m));for id,q:=range m{out=append(out,item{id,q})};sort.Slice(out,func(i,j int)bool{return out[i].id<out[j].id});return out,nil
}
func (s *Server) GetQuantity(ctx context.Context,r *inventoryv1.GetQuantityRequest)(*inventoryv1.GetQuantityResponse,error){
 if r.GetProductId()<=0{return nil,status.Error(codes.InvalidArgument,"product_id must be positive")};var q int32;e:=s.DB.QueryRow(ctx,"SELECT available FROM inventory WHERE product_id=$1",r.GetProductId()).Scan(&q);if e==pgx.ErrNoRows{return &inventoryv1.GetQuantityResponse{ProductId:r.ProductId,Found:false},nil};if e!=nil{return nil,status.Error(codes.Internal,"inventory lookup failed")};return &inventoryv1.GetQuantityResponse{ProductId:r.ProductId,Available:q,Found:true},nil
}
func (s *Server) Reserve(ctx context.Context,r *inventoryv1.ReserveRequest)(*inventoryv1.ReserveResponse,error){
 if r.GetReservationId()=="" {return nil,status.Error(codes.InvalidArgument,"reservation_id is required")};items,e:=normalize(r.GetItems());if e!=nil{return nil,status.Error(codes.InvalidArgument,e.Error())}
 tx,e:=s.DB.Begin(ctx);if e!=nil{return nil,status.Error(codes.Internal,"transaction failed")};defer tx.Rollback(ctx)
 tag,e:=tx.Exec(ctx,"INSERT INTO reservations(reservation_id,status) VALUES($1,'RESERVED') ON CONFLICT DO NOTHING",r.ReservationId);if e!=nil{return nil,status.Error(codes.Internal,"reservation insert failed")}
 if tag.RowsAffected()==0 {var st string;if e=tx.QueryRow(ctx,"SELECT status FROM reservations WHERE reservation_id=$1 FOR UPDATE",r.ReservationId).Scan(&st);e!=nil{return nil,status.Error(codes.Internal,"reservation lookup failed")};if st=="RELEASED"{return nil,status.Error(codes.FailedPrecondition,"reservation was released")};return &inventoryv1.ReserveResponse{Success:true,AlreadyReserved:true},nil}
 ids:=make([]int64,len(items));for i,x:=range items{ids[i]=x.id};rows,e:=tx.Query(ctx,"SELECT product_id,available FROM inventory WHERE product_id=ANY($1) ORDER BY product_id FOR UPDATE",ids);if e!=nil{return nil,status.Error(codes.Internal,"lock inventory failed")};available:=map[int64]int32{};for rows.Next(){var id int64;var q int32;if e=rows.Scan(&id,&q);e!=nil{return nil,status.Error(codes.Internal,"scan inventory failed")};available[id]=q};rows.Close()
 shortages:=[]*inventoryv1.Shortage{};for _,x:=range items{if available[x.id]<x.qty{shortages=append(shortages,&inventoryv1.Shortage{ProductId:x.id,Requested:x.qty,Available:available[x.id]})}};if len(shortages)>0{return &inventoryv1.ReserveResponse{Success:false,Shortages:shortages},nil}
 for _,x:=range items{if _,e=tx.Exec(ctx,"UPDATE inventory SET available=available-$1,updated_at=now() WHERE product_id=$2",x.qty,x.id);e!=nil{return nil,status.Error(codes.Internal,"update inventory failed")};if _,e=tx.Exec(ctx,"INSERT INTO reservation_items(reservation_id,product_id,quantity) VALUES($1,$2,$3)",r.ReservationId,x.id,x.qty);e!=nil{return nil,status.Error(codes.Internal,"save reservation items failed")}}
 if e=tx.Commit(ctx);e!=nil{return nil,status.Error(codes.Internal,"commit failed")};return &inventoryv1.ReserveResponse{Success:true},nil
}
func(s *Server) Release(ctx context.Context,r *inventoryv1.ReleaseRequest)(*inventoryv1.ReleaseResponse,error){
 if r.GetReservationId()==""{return nil,status.Error(codes.InvalidArgument,"reservation_id is required")};tx,e:=s.DB.Begin(ctx);if e!=nil{return nil,status.Error(codes.Internal,"transaction failed")};defer tx.Rollback(ctx);var st string;e=tx.QueryRow(ctx,"SELECT status FROM reservations WHERE reservation_id=$1 FOR UPDATE",r.ReservationId).Scan(&st);if e==pgx.ErrNoRows{return &inventoryv1.ReleaseResponse{Released:false},nil};if e!=nil{return nil,status.Error(codes.Internal,"reservation lookup failed")};if st=="RELEASED"{return &inventoryv1.ReleaseResponse{Released:false},nil};rows,e:=tx.Query(ctx,"SELECT product_id,quantity FROM reservation_items WHERE reservation_id=$1 ORDER BY product_id",r.ReservationId);if e!=nil{return nil,status.Error(codes.Internal,"items lookup failed")};items:=[]item{};for rows.Next(){var id int64;var q int32;if e=rows.Scan(&id,&q);e!=nil{return nil,status.Error(codes.Internal,"scan failed")};items=append(items,item{id,q})};rows.Close();for _,x:=range items{if _,e=tx.Exec(ctx,"UPDATE inventory SET available=available+$1,updated_at=now() WHERE product_id=$2",x.qty,x.id);e!=nil{return nil,status.Error(codes.Internal,"release update failed")}};if _,e=tx.Exec(ctx,"UPDATE reservations SET status='RELEASED' WHERE reservation_id=$1",r.ReservationId);e!=nil{return nil,status.Error(codes.Internal,"release failed")};if e=tx.Commit(ctx);e!=nil{return nil,status.Error(codes.Internal,"commit failed")};return &inventoryv1.ReleaseResponse{Released:true},nil}
func(s *Server) SetStock(ctx context.Context,r *inventoryv1.SetStockRequest)(*inventoryv1.SetStockResponse,error){if r.GetProductId()<=0||r.GetQuantity()<0{return nil,status.Error(codes.InvalidArgument,"product_id must be positive and quantity non-negative")};_,e:=s.DB.Exec(ctx,"INSERT INTO inventory(product_id,available,updated_at) VALUES($1,$2,now()) ON CONFLICT(product_id) DO UPDATE SET available=excluded.available,updated_at=now()",r.ProductId,r.Quantity);if e!=nil{return nil,status.Error(codes.Internal,"set stock failed")};return &inventoryv1.SetStockResponse{ProductId:r.ProductId,Available:r.Quantity},nil}

// MaxBatch bounds GetStockBatch so one call cannot ask for an unbounded ANY(...) list.
const MaxBatch = 500
const batchDeadline = 2 * time.Second

// dedupeIDs validates and collapses duplicate ids, keeping first-seen order.
func dedupeIDs(in []int64) ([]int64, error) {
 if len(in) > MaxBatch { return nil, fmt.Errorf("at most %d product ids per call", MaxBatch) }
 seen := make(map[int64]struct{}, len(in)); out := make([]int64, 0, len(in))
 for _, id := range in {
  if id <= 0 { return nil, fmt.Errorf("product ids must be positive") }
  if _, ok := seen[id]; ok { continue }
  seen[id] = struct{}{}; out = append(out, id)
 }
 return out, nil
}

// GetStockBatch answers the stock of many products with ONE query (WHERE product_id = ANY($1)).
func (s *Server) GetStockBatch(ctx context.Context, r *inventoryv1.GetStockBatchRequest) (*inventoryv1.GetStockBatchResponse, error) {
 ids, e := dedupeIDs(r.GetProductIds()); if e != nil { return nil, status.Error(codes.InvalidArgument, e.Error()) }
 if len(ids) == 0 { return &inventoryv1.GetStockBatchResponse{}, nil }
 ctx, cancel := context.WithTimeout(ctx, batchDeadline); defer cancel() // never longer than the client deadline
 rows, e := s.DB.Query(ctx, "SELECT product_id, available FROM inventory WHERE product_id = ANY($1)", ids)
 if e != nil { return nil, status.Error(codes.Internal, "stock lookup failed") }
 defer rows.Close()
 found := make(map[int64]int32, len(ids))
 for rows.Next() { var id int64; var q int32; if e = rows.Scan(&id, &q); e != nil { return nil, status.Error(codes.Internal, "scan stock failed") }; found[id] = q }
 if e = rows.Err(); e != nil { return nil, status.Error(codes.Internal, "stock lookup failed") }
 out := make([]*inventoryv1.StockItem, 0, len(ids))
 for _, id := range ids { q, ok := found[id]; out = append(out, &inventoryv1.StockItem{ProductId: id, Available: q, Found: ok}) }
 return &inventoryv1.GetStockBatchResponse{Items: out}, nil
}
