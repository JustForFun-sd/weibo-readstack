FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
COPY . .
ENV STATE_DIR=/data
EXPOSE 9000
CMD ["python", "app.py"]
