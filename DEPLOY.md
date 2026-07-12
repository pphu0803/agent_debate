# 部署到腾讯云服务器

## 前置条件

- 一台腾讯云服务器（已安装 Docker + Docker Compose）
- 域名 `debate.healthcompanion.com.cn` 已解析到服务器公网 IP
- 安全组已放行 **80** 和 **443** 端口

## 安全组配置（腾讯云控制台）

在服务器的安全组里，添加以下入站规则：

| 端口 | 来源 | 协议 | 说明 |
|------|------|------|------|
| 80 | 0.0.0.0/0 | TCP | HTTP（跳转HTTPS + 证书验证） |
| 443 | 0.0.0.0/0 | TCP | HTTPS |

> 不需要开放 8000 和 27017 端口，后端和数据库只在 Docker 内部网络通信。

## 部署步骤

### 1. 把代码传到服务器

```bash
# 在服务器上
git clone https://github.com/pphu0803/agent_debate.git
cd agent_debate
```

或用 scp 上传整个目录：
```bash
# 在本地（打包时排除venv等大文件）
tar --exclude='venv' --exclude='.git' --exclude='__pycache__' \
    -czf agent_debate.tar.gz agent_debate/
scp agent_debate.tar.gz user@服务器IP:~/

# 在服务器上
tar -xzf agent_debate.tar.gz && cd agent_debate
```

### 2. 一键部署（含自动申请HTTPS证书）

```bash
# 安装 Docker（如果还没装）
curl -fsSL https://get.docker.com | sh

# 执行部署脚本
bash init-ssl.sh your-email@example.com
```

脚本会自动：
1. 申请 Let's Encrypt 免费 SSL 证书
2. 构建后端 Docker 镜像
3. 启动 MongoDB + 后端 + Nginx 三个容器

### 3. 配置 API Key

打开 `https://debate.healthcompanion.com.cn` → 点左下角「设置」→ 填入 API Key → 保存

### 4. 设置访问密码（重要！防止他人查看你的辩论记录）

部署前，在服务器上创建 `.env` 文件设置访问密码：

```bash
# 在项目根目录创建 .env（docker-compose会自动读取）
echo 'ACCESS_PASSWORD=你的强密码' >> .env
```

设置后，任何人访问网站都需要先输入密码登录。不设置则无鉴权（仅适合本地开发）。

### 完成！

---

## 手动操作（如果一键脚本出问题）

### 单独申请证书

```bash
# 停掉占用80端口的服务
docker compose -f docker-compose.prod.yml down

# 用certbot申请
docker run --rm -p 80:80 \
    -v "$(pwd)/nginx/certs:/etc/letsencrypt/live/debate.healthcompanion.com.cn" \
    certbot/certbot certonly --standalone \
    -d debate.healthcompanion.com.cn \
    --email your-email@example.com --agree-tos --no-eff-email --non-interactive
```

### 启动服务

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

### 查看日志

```bash
# 实时日志
docker compose -f docker-compose.prod.yml logs -f

# 只看后端
docker compose -f docker-compose.prod.yml logs -f backend
```

---

## 常见问题

### Q: 证书申请失败？
**A:** 确认域名已正确解析到服务器IP，且80端口未被占用：
```bash
dig debate.healthcompanion.com.cn +short  # 应返回服务器IP
ss -tlnp | grep :80                       # 应为空
```

### Q: HTTPS 访问不了？
**A:** 检查腾讯云安全组是否放行了443端口。

### Q: SSE 流式推送断开？
**A:** nginx 配置已针对 SSE 优化（关闭缓冲、1小时超时）。如果仍有问题，检查是否有 CDN/防火墙在中间缓存。

### Q: 如何更新代码后重新部署？
```bash
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

### Q: 证书过期怎么续期？
```bash
docker run --rm \
    -v "$(pwd)/nginx/certs:/etc/letsencrypt/live/debate.healthcompanion.com.cn" \
    certbot/certbot renew
docker compose -f docker-compose.prod.yml restart nginx
```
（Let's Encrypt 证书有效期90天，建议设置 crontab 自动续期）
