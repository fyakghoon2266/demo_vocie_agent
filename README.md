## 環境需求

- python 3.12版本（3.10以上都可以）
- 可以用docker建立，os要用linux或是macos


## 內容簡單說明：

前端頁面置放在templates/index.html裡面，前端跟後端ap（main.py or main_litellm.py）都是透過ws建立連線，後端ap跟litellm或是真正的model連線也是需要透過websockets，但程式裡面也一個地方沒有寫好，當前端點選結束通話的時候只是前端跟後端ap的ws連線中斷而已，ap程式沒有自動地跟語言模型這邊中斷，這一點需要注意一下．

## 程式啟動語法：

uvicorn main_litellm:app --reload --port 5000  <- 連線到litellm的ap

uvicorn main:app --reload --port 5000  <- 連線到azure openai 的