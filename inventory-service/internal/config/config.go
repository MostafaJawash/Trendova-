package config
import "os"
type Config struct { DatabaseURL, Port string }
func Load() Config { p:=os.Getenv("GRPC_PORT"); if p=="" { p="50051" }; return Config{DatabaseURL:os.Getenv("DATABASE_URL"),Port:p} }
