$ErrorActionPreference = 'Stop'
$smokeDir = Join-Path ([System.IO.Path]::GetTempPath()) ('trendova-smoke-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $smokeDir | Out-Null
$responseFile = Join-Path $smokeDir 'response.json'
$bodyFile = Join-Path $smokeDir 'body.json'
$imageFile = Join-Path $smokeDir 'image.png'
[System.IO.File]::WriteAllBytes($imageFile, [Convert]::FromBase64String('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEklEQVR4nGNkYPjPwMDAxAAGAAsfAQMU4wsAAAAAAElFTkSuQmCC'))
$base = 'http://localhost:8000/api/v1'
$suffix = [guid]::NewGuid().ToString('N').Substring(0,8)

function Call-Curl($label, $method, $path, $body, $token, $expected, $multipart=$false) {
    $curlArgs = @('-sS','-o',$responseFile,'-w','%{http_code}','-X',$method)
    if ($token) { $curlArgs += @('-H', "Authorization: Bearer $token") }
    if ($multipart) {
        foreach ($key in $body.Keys) { $curlArgs += @('-F', "${key}=$($body[$key])") }
        $curlArgs += @('-F', "image=@$imageFile;type=image/png")
    } elseif ($null -ne $body) {
        $body | ConvertTo-Json -Depth 10 -Compress | Set-Content -LiteralPath $bodyFile -Encoding utf8
        $curlArgs += @('-H','Content-Type: application/json','--data-binary',"@$bodyFile")
    }
    $curlArgs += ($base + $path)
    $status = & curl.exe @curlArgs
    if ($LASTEXITCODE -ne 0) { throw "curl failed for $label" }
    Write-Host "$label $status"
    if ([int]$status -ne $expected) { throw "$label expected $expected; got $status : $(Get-Content -Raw $responseFile)" }
    if ($expected -ne 204) { return (Get-Content -Raw $responseFile | ConvertFrom-Json) }
}

$admin = Call-Curl 'admin login' 'POST' '/auth/login' @{email='admin@example.com';password='ChangeMe123!'} $null 200
$adminToken = $admin.access_token
$firstEmail = "smoke_$suffix@example.com"
$secondEmail = "other_$suffix@example.com"
Call-Curl 'register user' 'POST' '/auth/register' @{email=$firstEmail;password='password123';name='Smoke User'} $null 201 | Out-Null
Call-Curl 'register other user' 'POST' '/auth/register' @{email=$secondEmail;password='password123';name='Other User'} $null 201 | Out-Null
$user = Call-Curl 'user login' 'POST' '/auth/login' @{email=$firstEmail;password='password123'} $null 200
$other = Call-Curl 'other login' 'POST' '/auth/login' @{email=$secondEmail;password='password123'} $null 200
$category = Call-Curl 'create category' 'POST' '/categories' @{name="Smoke category $suffix";description='Arabic مرحبا'} $adminToken 201
$product = Call-Curl 'create product with image' 'POST' '/products' @{name="Smoke phone $suffix";description='Smart device';price='15.75';category_id=$category.id;initial_quantity=5} $adminToken 201 $true
Call-Curl 'filter products' 'GET' "/products?category=$($category.id)&minPrice=15&maxPrice=16&search=SMOKE&page=1&limit=10" $null $user.access_token 200 | Out-Null
$order = Call-Curl 'create order' 'POST' '/orders' @{items=@(@{product_id=$product.id;quantity=2;price='0.01'})} $user.access_token 201
Call-Curl 'other user reads order' 'GET' "/orders/$($order.id)" $null $other.access_token 403 | Out-Null
Call-Curl 'user changes status' 'PATCH' "/orders/$($order.id)/status" @{status='confirmed'} $user.access_token 403 | Out-Null
Call-Curl 'admin changes status' 'PATCH' "/orders/$($order.id)/status" @{status='confirmed'} $adminToken 200 | Out-Null
Call-Curl 'logout' 'POST' '/auth/logout' $null $user.access_token 204 | Out-Null
Call-Curl 'reuse logged out token' 'GET' '/auth/me' $null $user.access_token 401 | Out-Null
for ($n=1; $n -le 6; $n++) {
    $expected = if ($n -eq 6) {429} else {401}
    Call-Curl "wrong login $n" 'POST' '/auth/login' @{email=$secondEmail;password='wrong-password'} $null $expected | Out-Null
}
