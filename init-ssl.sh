#!/bin/bash
# ============================================
# 思想孵化机 - 一键部署脚本
# 在腾讯云服务器上运行：bash init-ssl.sh
# ============================================
set -e

DOMAIN="debate.healthcompanion.com.cn"
EMAIL="${1:-admin@healthcompanion.com.cn}"

echo "========================================"
echo "  思想孵化机 - 部署脚本"
echo "  域名: $DOMAIN"
echo "  邮箱: $EMAIL (用于Let's Encrypt证书)"
echo "========================================"
echo ""

# ============ 1. 检查环境 ============
echo "[1/5] 检查环境..."
if ! command -v docker &> /dev/null; then
    echo "❌ Docker未安装，请先安装: curl -fsSL https://get.docker.com | sh"
    exit 1
fi
if ! docker compose version &> /dev/null; then
    echo "❌ Docker Compose未安装，请参考: https://docs.docker.com/compose/install/"
    exit 1
fi
echo "✓ Docker 和 Docker Compose 已就绪"
echo ""

# ============ 2. 申请SSL证书 ============
echo "[2/5] 申请Let's Encrypt SSL证书..."
echo "  (需要先临时启动nginx的80端口来验证域名)"

# 先创建证书目录
mkdir -p nginx/certs/acme/.well-known/acme-challenge

# 用 certbot 申请证书（standalone模式，临时占用80端口）
echo "  停止可能占用80端口的服务..."
docker compose -f docker-compose.prod.yml down 2>/dev/null || true

echo "  用certbot申请证书（standalone模式）..."
docker run --rm \
    -p 80:80 \
    -v "$(pwd)/nginx/certs:/etc/letsencrypt/live/$DOMAIN" \
    certbot/certbot certonly \
    --standalone \
    -d "$DOMAIN" \
    -d "www.$DOMAIN" \
    --email "$EMAIL" \
    --agree-tos \
    --no-eff-email \
    --non-interactive

# certbot输出的文件结构是 /etc/letsencrypt/live/域名/fullchain.pem 和 privkey.pem
# 上面的volume映射后，文件会出现在 nginx/certs/fullchain.pem 和 privkey.pem
echo "✓ SSL证书已申请"
echo ""

# ============ 3. 构建后端镜像 ============
echo "[3/5] 构建后端Docker镜像..."
docker compose -f docker-compose.prod.yml build backend
echo "✓ 镜像构建完成"
echo ""

# ============ 4. 启动服务 ============
echo "[4/5] 启动所有服务..."
docker compose -f docker-compose.prod.yml up -d
echo "✓ 服务已启动"
echo ""

# ============ 5. 等待并验证 ============
echo "[5/5] 等待服务就绪..."
sleep 5

# 健康检查
for i in 1 2 3 4 5; do
    if curl -sf http://localhost:8000/api/health &> /dev/null; then
        echo "✓ 后端健康检查通过"
        break
    fi
    echo "  等待后端启动... ($i/5)"
    sleep 3
done

echo ""
echo "========================================"
echo "  🎉 部署完成！"
echo ""
echo "  访问地址: https://$DOMAIN"
echo ""
echo "  首次使用："
echo "  1. 打开上面的地址"
echo "  2. 点击左下角「设置」"
echo "  3. 填入你的 LLM API Key"
echo "  4. 开始辩论！"
echo ""
echo "  常用命令："
echo "  查看日志: docker compose -f docker-compose.prod.yml logs -f"
echo "  重启服务: docker compose -f docker-compose.prod.yml restart"
echo "  停止服务: docker compose -f docker-compose.prod.yml down"
echo "========================================"
