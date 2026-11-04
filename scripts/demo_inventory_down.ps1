$ErrorActionPreference = 'Stop'
$base = $env:API_URL; if (-not $base) { $base = 'http://localhost:8000/api/v1' }
function Json($method, $path, $body, $token) {
  $headers = @{}; if ($token) { $headers.Authorization = "Bearer $token" }
  $args = @{ Method=$method; Uri=($base+$path); Headers=$headers; UseBasicParsing=$true }
  if ($null -ne $body) { $args.ContentType='application/json'; $args.Body=($body | ConvertTo-Json -Depth 10 -Compress) }
  try { return Invoke-WebRequest @args } catch {
    $response = $_.Exception.Response
    $reader = [IO.StreamReader]::new($response.GetResponseStream())
    $content = $reader.ReadToEnd()
    if (-not $content) { $content = $_.ErrorDetails.Message }
    return [pscustomobject]@{ StatusCode=[int]$response.StatusCode; Content=$content }
  }
}
$login = Json 'POST' '/auth/login' @{email='admin@example.com';password='ChangeMe123!'} $null
if ([int]$login.StatusCode -ne 200) { throw "admin login failed: $($login.StatusCode)" }
$token = ($login.Content | ConvertFrom-Json).access_token
$products = Json 'GET' '/products?limit=1' $null $token
$productId = ($products.Content | ConvertFrom-Json).items[0].id
docker compose stop inventory-service | Out-Host
$watch = [Diagnostics.Stopwatch]::StartNew()
$order = Json 'POST' '/orders' @{items=@(@{product_id=$productId;quantity=1})} $token
$watch.Stop(); $orderJson = $order.Content | ConvertFrom-Json
Write-Host "POST /orders: $([int]$order.StatusCode) $($orderJson.error.code) elapsed_ms=$($watch.ElapsedMilliseconds)"
if ([int]$order.StatusCode -ne 503 -or $orderJson.error.code -ne 'INVENTORY_UNAVAILABLE') { throw 'expected 503 INVENTORY_UNAVAILABLE' }
$product = Json 'GET' "/products/$productId" $null $token; $stock = ($product.Content | ConvertFrom-Json).stock
Write-Host "GET /products/${productId}: $([int]$product.StatusCode) stock.status=$($stock.status)"
if ([int]$product.StatusCode -ne 200 -or $stock.status -ne 'unavailable') { throw 'expected graceful unavailable stock response' }
docker compose start inventory-service | Out-Host
for ($i=0; $i -lt 15; $i++) { Start-Sleep -Seconds 1; $product = Json 'GET' "/products/$productId" $null $token; if (($product.Content | ConvertFrom-Json).stock.status -eq 'available') { break } }
$stock = ($product.Content | ConvertFrom-Json).stock
Write-Host "Recovery: $([int]$product.StatusCode) stock.status=$($stock.status)"
if ($stock.status -ne 'available') { throw 'warehouse did not recover' }
