# DOGE 币本位 OI 提醒 — 容器镜像
# 用法: 把本文件与 doge_oi_alert_v2.py 放同一目录, 上传到 Railway / Render / Fly.io 等
# 注意: 选择 "Worker / Background Worker" 类型, 不要选 Web Service(本程序不监听端口)
FROM python:3.11-slim

ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DOGE_STATE_DIR=/data

RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# 状态文件目录: docker-compose 会挂一个 volume 到这里, 单机 docker run 也可用
RUN mkdir -p /data
COPY doge_oi_alert_v2.py /app/doge_oi_alert_v2.py
# 模式开关必须一起打包进镜像, 否则容器读不到 mode.conf
COPY mode.conf /app/mode.conf

# 纯标准库, 无需 pip install
# token / chat_id 通过平台面板的环境变量注入, 绝不写进镜像
CMD ["python3", "doge_oi_alert_v2.py"]
