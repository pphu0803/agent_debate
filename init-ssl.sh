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

# 准备目录
# - letsencrypt: certbot 完整工作目录。必须挂载整个 /etc/letsencrypt，
#   不能只挂 live/<域名>/ 子目录，否则 certbot 会因 lineage 目录已存在
#   报 "live directory exists for <域名>" 而失败。
# - nginx/certs: nginx 容器最终读取证书的目录
mkdir -p nginx/certs letsencrypt

# 停止可能占用80端口的服务（certbot standalone 需要绑定80端口做域名验证）
echo "  停止可能占用80端口的服务..."
docker compose -f docker-compose.prod.yml down 2>/dev/null || true

echo "  用 certbot 申请证书（standalone模式，临时占用80端口验证域名）..."
docker run --rm \
    -p 80:80 \
    -v "$(pwd)/letsencrypt:/etc/letsencrypt" \
    certbot/certbot certonly \
    --standalone \
    -d "$DOMAIN" \
    --email "$EMAIL" \
    --agree-tos \
    --no-eff-email \
    --non-interactive

# certbot 生成的证书在 letsencrypt/live/<域名>/ 下，是指向 archive/ 的软链接。
# nginx 容器只挂载 nginx/certs，软链接目标在挂载范围外会失效，
# 因此用 cp -L 跟随软链接拷贝真实文件内容到 nginx/certs/。
cp -L letsencrypt/live/$DOMAIN/fullchain.pem nginx/certs/fullchain.pem
cp -L letsencrypt/live/$DOMAIN/privkey.pem nginx/certs/privkey.pem
chmod 644 nginx/certs/fullchain.pem
chmod 600 nginx/certs/privkey.pem

echo "✓ SSL证书已申请并拷贝到 nginx/certs/"
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
    # prod 模式下 backend 仅 expose 不映射到宿主机，经 nginx(443) 验证整个链路。
    # -k 跳过证书校验：localhost 访问时 Host 与证书域名不匹配。
    if curl -sfk https://localhost/api/health &> /dev/null; then
        echo "✓ 服务健康检查通过（HTTPS 经 nginx → backend）"
        break
    fi
    echo "  等待服务启动... ($i/5)"
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
