package store
import (
 "context"
 "github.com/jackc/pgx/v5/pgxpool"
)
const schema = `CREATE TABLE IF NOT EXISTS inventory(product_id BIGINT PRIMARY KEY, available INT NOT NULL CHECK (available >= 0), updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS reservations(reservation_id TEXT PRIMARY KEY, status TEXT NOT NULL CHECK (status IN ('RESERVED','RELEASED')), created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS reservation_items(reservation_id TEXT REFERENCES reservations(reservation_id), product_id BIGINT, quantity INT NOT NULL CHECK(quantity>0), PRIMARY KEY(reservation_id,product_id));`
func Connect(ctx context.Context, url string) (*pgxpool.Pool,error) { p,e:=pgxpool.New(ctx,url);if e!=nil{return nil,e};_,e=p.Exec(ctx,schema);return p,e }
