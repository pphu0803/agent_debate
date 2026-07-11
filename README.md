# 思想孵化机

> AI Agent 辩论机器 — 让三个角色各异的AI Agent围绕你的问题展开多轮辩论，孵化出更深层的思考。

## 功能特性

- **三Agent辩论系统**：激进的创新者、严厉的反对者、保守的学者循环发言
- **实时流式输出**：SSE实时推送，查看Agent"思考中"状态
- **智能上下文压缩**：当发言记录过长时自动总结压缩，保持讨论连贯
- **动态评分机制**：每轮发言后各Agent给出接受度评分（1-10分），三方均超过阈值即达成共识
- **自动生成报告**：辩论结束后生成结构化的思想孵化报告
- **历史记录管理**：所有辩论自动保存，可随时查看历史
- **可配置**：支持OpenAI、Azure OpenAI、Ollama等兼容API
- **Docker一键部署**：包含MongoDB + 后端的完整部署方案

## 架构

```
┌─────────────┐     SSE      ┌──────────────┐
│   前端 (JS)  │◄───────────►│  后端 (Python) │
│  index.html  │   REST API  │   FastAPI     │
│  style.css   │             │   Agents       │
│  app.js      │             │   LLM Service  │
└─────────────┘             └──────┬────────┘
                                    │
                            ┌───────▼────────┐
                            │  MongoDB        │
                            │  (辩论数据存储)   │
                            └────────────────┘
```

## 快速开始

### 方式一：Docker Compose（推荐）

1. 创建环境变量文件：
```bash
cp backend/.env.example .env
# 编辑 .env，填入你的 OPENAI_API_KEY
```

2. 启动服务：
```bash
docker-compose up -d
```

3. 打开浏览器访问 `http://localhost:8000`

### 方式二：本地开发

1. **启动MongoDB**（可用Docker）：
```bash
docker run -d -p 27017:27017 --name mongo mongo:7
```

2. **安装后端依赖**：
```bash
cd backend
cp .env.example .env
# 编辑 .env 填入配置
pip install -r requirements.txt
```

3. **启动后端**：
```bash
python main.py
```

4. **访问前端**：打开 `http://localhost:8000`（后端会自动托管前端静态文件）

## 使用流程

1. 点击右上角**设置**图标，填入API Key和模型配置
2. 在左侧输入框中输入你的想法、问题或议题
3. 可选：调整最大轮次和共识阈值
4. 点击**开始辩论**
5. 观察三个Agent轮流发言，实时查看评分变化
6. 当三方评分均超过阈值，辩论自动结束并生成报告
7. 可随时点击**终止辩论**手动结束
8. 点击右上角**历史**图标查看过往辩论记录

## 三个Agent角色

| 角色 | 特点 | 温度 |
|------|------|------|
| 激进的创新者 | 提出新概念、新理论、新机制，跨学科思考 | 0.9 |
| 严厉的反对者 | 批判逻辑漏洞、矛盾、证据不足，提出反例 | 0.3 |
| 保守的学者 | 参照现有知识和文献，谨慎评估，指出交叉 | 0.5 |

## API接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/debates` | 创建新辩论 |
| GET | `/api/debates/{id}/stream` | SSE流式获取辩论更新 |
| GET | `/api/debates/{id}` | 获取辩论详情 |
| GET | `/api/debates` | 获取辩论列表 |
| POST | `/api/debates/{id}/stop` | 终止辩论 |
| GET | `/api/config` | 获取配置状态 |
| POST | `/api/config` | 更新LLM配置 |
| GET | `/api/agents` | 获取Agent信息 |

## 支持的LLM

- OpenAI (GPT-4o, GPT-4, GPT-3.5-turbo等)
- Azure OpenAI
- 本地Ollama (修改 `OPENAI_API_BASE` 为 `http://localhost:11434/v1`)
- 任何OpenAI兼容API

## 项目结构

```
├── backend/
│   ├── main.py              # FastAPI主应用
│   ├── config.py            # 配置管理
│   ├── models.py            # 数据模型
│   ├── agents.py            # 三个Agent定义
│   ├── llm_service.py       # LLM调用服务
│   ├── debate_service.py    # 辩论编排服务
│   ├── requirements.txt     # Python依赖
│   ├── Dockerfile
│   └── .env.example
├── frontend/
│   ├── index.html           # 主页面
│   ├── css/style.css        # 样式表
│   └── js/app.js            # 前端逻辑
├── docker-compose.yml       # Docker编排
└── README.md
```

## 技术栈

- **前端**：原生HTML/CSS/JS + marked.js (Markdown渲染)
- **后端**：Python + FastAPI + SSE
- **数据库**：MongoDB (Motor异步驱动)
- **LLM**：OpenAI兼容API (openai SDK)
- **部署**：Docker + Docker Compose
