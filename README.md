# 新北樂圾車 Home Assistant Integration

[![GitHub Release](https://img.shields.io/github/release/PinLin/new-taipei-rubbish-homeassistant.svg?style=flat-square)](https://github.com/PinLin/new-taipei-rubbish-homeassistant/releases)
[![HACS Badge](https://img.shields.io/badge/HACS-Custom-orange.svg?style=flat-square)](https://github.com/hacs/integration)
[![MIT License](https://img.shields.io/badge/License-MIT-blue.svg?style=flat-square)](LICENSE)

將新北市垃圾車清運資訊整合到 Home Assistant，提供清運時間、垃圾車狀態與預估到站時間的即時監控。

## 功能特色

- **地圖選點**：以地圖選擇位置，自動列出最近的 20 個收運點。
- **收運點合併**：同一實體收運點會自動合併多條路線，集中顯示所有表定時間。
- **即時清運資訊**：顯示 `表定清運時間`、`垃圾車狀態`、`預估抵達時間` 與最近垃圾車距離。
- **過站判斷**：提供 `垃圾車已離開` binary sensor，標示官網即時資料是否已顯示該點過站。
- **今日收運項目**：顯示今日是否收一般垃圾、資源回收與廚餘。
- **路線診斷**：每條已儲存路線會建立診斷用 binary sensor，顯示該路線目前是否啟用。
- **手動更新服務**：提供 `ntpc_rubbish.update`，可更新全部收運點或指定 `point_ids`。

## 安裝方式

### HACS 安裝（推薦）

[![Add to HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=PinLin&repository=new-taipei-rubbish-homeassistant&category=integration)

1. 在 Home Assistant 中開啟 **HACS**。
2. 選擇右上角選單中的 **Custom repositories**。
3. 加入 `https://github.com/PinLin/new-taipei-rubbish-homeassistant`，類別選 **Integration**。
4. 安裝完成後重新啟動 Home Assistant。

### 手動安裝

1. 將 `custom_components/ntpc_rubbish/` 複製到 Home Assistant 的 `config/custom_components/`。
2. 重新啟動 Home Assistant。

## 資料來源與 API

目前整合實際使用 3 個 API，分成靜態路線資料與官網即時資料兩類：

1. 路線資料（設定流程與靜態清運資訊）
   `GET https://data.ntpc.gov.tw/api/datasets/edc3ad26-8ae7-4916-a00b-bc6048d19bf8/json`

2. 官網即時路線資料（指定路線的車輛位置、狀態、到站資訊）
   `POST https://crd-rubbish.epd.ntpc.gov.tw/WebAPI/GetArrival`

3. 官網地圖周邊即時資料（指定座標附近 500 公尺的清運點與即時資訊）
   `POST https://crd-rubbish.epd.ntpc.gov.tw/WebAPI/GetAroundPoints`

目前實作分工如下：

- `config flow` 只使用開放資料 API，因為需要完整的 `lineid`、`rank`、`linename`、座標與每週清運欄位，才能建立可追蹤的收運點設定
- 即時狀態、最近車輛位置、預估抵達時間則優先使用官網 API
- 會先查 `GetAroundPoints`，若回傳結果中沒有目前設定的路線，再退回 `GetArrival`

補充：官網網頁的地址搜尋本身是先用 Google Maps geocoding 轉座標，再查附近清運點，不是獨立的文字搜尋 API；目前整合沒有接這段地址搜尋流程。

## 設定流程

[![Add Integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=ntpc_rubbish)

前往 **設定 → 裝置與服務 → 新增整合 → 新北市垃圾車**：

1. 在地圖上放置位置
2. 從最近的收運點清單中選擇一個收運點
3. 清單格式為 `距離｜收運點（行政區 里）｜所有表定時間`
4. 若該收運點有多條路線，再選擇要啟用哪些路線

設定流程目前完全依賴新北開放資料，不直接呼叫官網即時 API。流程大致如下：

- 先抓整份開放資料路線清單
- 依使用者輸入的座標計算距離，找出最近的收運點
- 將同名且同座標的多筆 route row 合併成同一個實體收運點
- 若同地點有多條路線，保留各自的 `lineid`、`rank`、`linename` 與表定時間，讓使用者選擇要啟用哪些路線

因此同一收運點一天有多個時段時，只需建立一個整合條目；後續 coordinator 再依已保存的路線資訊去查官網即時資料。

## 建立的實體

每個收運點會建立固定清運資訊實體，並依該收運點保存的路線數量額外建立診斷實體。

| 實體 | 類型 | 說明 |
|------|------|------|
| 垃圾車距離 | `sensor` | 最近垃圾車與收運點的直線距離（公尺） |
| 表定清運時間 | `sensor` | 目前顯示上下文對應的表定時間，例如 `今天 19:33` |
| 垃圾車狀態 | `sensor` | 官網狀態，例如 `執勤中`、`前往焚化廠`、`非收運時間` |
| 預估抵達時間 | `sensor` | 優先使用官網 ETA 的預估到達時間，例如 `今天 17:09` |
| 今日收垃圾 | `binary_sensor` | 今日是否收一般垃圾 |
| 今日資源回收 | `binary_sensor` | 今日是否收資源回收 |
| 今日廚餘回收 | `binary_sensor` | 今日是否收廚餘 |
| 垃圾車已離開 | `binary_sensor` | 官網即時資料顯示該清運點已過站時為 `on` |
| 路線 | `binary_sensor`（診斷） | 每條路線是否啟用，名稱顯示表定時間、路線名、rank 與 lineid |

`entity_id` 會依清運點座標建立穩定 ID，不使用中文名稱轉拼音。例如：

```text
sensor.ntpc_rubbish_24_99145_121_46071_next_collection
binary_sensor.ntpc_rubbish_24_99145_121_46071_truck_departed
binary_sensor.ntpc_rubbish_24_99145_121_46071_route_220057_51_enabled
```

## 裝置與收運點 ID

- 裝置名稱會顯示收運點名稱，例如 `範例路100號`。
- 裝置型號欄位會顯示收運點 ID，也就是座標格式的 `point_id`，例如 `25.00000_121.00000`。
- 實體屬性也會顯示 `point_id`，可用於手動更新服務。
- 路線啟用狀態會顯示在裝置頁的「診斷資料」區。

## 服務

### `ntpc_rubbish.update`

手動觸發更新垃圾車資料。可指定 `point_ids` 清單只更新特定收運點，留空則更新全部。

```yaml
service: ntpc_rubbish.update
data:
  point_ids:
    - "25.00000_121.00000"
```

## 自動化範例

### 垃圾車狀態通知

```yaml
automation:
  - alias: 垃圾車狀態提醒
    trigger:
      - platform: state
        entity_id: sensor.ntpc_rubbish_24_99145_121_46071_collection_status
    action:
      - service: notify.mobile_app_your_phone
        data:
          message: >
            目前狀態：{{ states('sensor.ntpc_rubbish_24_99145_121_46071_collection_status') }}
```

### 早晨提醒今日收運項目

```yaml
automation:
  - alias: 今日垃圾提醒
    trigger:
      - platform: time
        at: "07:30:00"
    condition:
      - condition: or
        conditions:
          - condition: state
            entity_id: binary_sensor.ntpc_rubbish_24_99145_121_46071_garbage_today
            state: "on"
          - condition: state
            entity_id: binary_sensor.ntpc_rubbish_24_99145_121_46071_recycling_today
            state: "on"
          - condition: state
            entity_id: binary_sensor.ntpc_rubbish_24_99145_121_46071_food_scraps_today
            state: "on"
    action:
      - service: notify.mobile_app_your_phone
        data:
          message: >
            今天的表定清運時間是 {{ states('sensor.ntpc_rubbish_24_99145_121_46071_next_collection') }}。
```

## 開發檢查

```bash
python -m compileall custom_components/ntpc_rubbish
python -m py_compile custom_components/ntpc_rubbish/*.py
python -m pytest tests/ -v
```

## 授權

MIT License
