
# native_app/dashboard_native.py
import flet as ft
from flet_charts import (
    CandlestickChart, 
    LineChart, 
    CandlestickChartSpot, 
    LineChartData, 
    LineChartDataPoint, 
    ChartAxis, 
    ChartGridLines
)
import asyncio
from data_manager import DataManager

# Global Manager
manager = DataManager()

async def main(page: ft.Page):
    page.title = "Inflow Dashboard (Native Charts)"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 10
    page.spacing = 10
    
    # State controls
    dd_timeframe = ft.Dropdown(
        options=[ft.dropdown.Option("1 Minute"), ft.dropdown.Option("5 Minutes")],
        value="5 Minutes",
        width=150,
        label="Timeframe"
    )
    
    sb_window = ft.TextField(value="5", label="Rolling Window", width=100, keyboard_type=ft.KeyboardType.NUMBER)
    sb_days = ft.TextField(value="1", label="Days", width=100, keyboard_type=ft.KeyboardType.NUMBER)
    chk_refresh = ft.Checkbox(label="Auto-Refresh (5m)", value=True)
    status_txt = ft.Text("Ready", size=12, color="grey")

    # Chart Controls
    # We will update these charts' data properties directly
    
    # 1. Candlestick Chart
    price_chart = CandlestickChart(
        expand=True,
        spots=[],
        bottom_axis=ChartAxis(), # labels_interval removed
        vertical_grid_lines=ChartGridLines(width=1, color="white12"),
        horizontal_grid_lines=ChartGridLines(width=1, color="white12"),
    )
    
    # 2. Inflow Chart (Line)
    inflow_chart = LineChart(
        expand=True,
        data_series=[],
        left_axis=ChartAxis(),
        bottom_axis=ChartAxis(),
        horizontal_grid_lines=ChartGridLines(width=1, color="white12"),
    )

    async def refresh_data(e=None):
        status_txt.value = "Fetching data..."
        page.update()
        
        try:
            days = int(sb_days.value)
            tf_str = dd_timeframe.value
            win = int(sb_window.value)
            
            tf_map = {"1 Minute": "1m", "5 Minutes": "5m"}
            tf = tf_map.get(tf_str, "5m")
            
            # Fetch Data
            p_data, i_data, l_data = await asyncio.to_thread(manager.fetch_data, days, tf, win)
            
            # Update Price Chart
            spots = []
            if p_data:
                for p in p_data:
                    # Time is unix timestamp, huge number. 
                    # We might need to map it to index 0..N for clean rendering, and use labels for time
                    # But for now, let's use the timestamp directly and see if it scales.
                    x_val = p['time']
                    spots.append(CandlestickChartSpot(
                        x=float(x_val),
                        open=p['open'],
                        high=p['high'],
                        low=p['low'],
                        close=p['close']
                    ))
            
            price_chart.spots = spots
            # Auto-scale axes (simple logic: min/max)
            if spots:
                xs = [s.x for s in spots]
                ys = [s.high for s in spots] + [s.low for s in spots]
                price_chart.min_x = min(xs)
                price_chart.max_x = max(xs)
                price_chart.min_y = min(ys) * 0.999 # Add some padding
                price_chart.max_y = max(ys) * 1.001

            # Update Inflow Chart
            # We have two series: Rolling BTC (inflow) and Lagged
            series_inflow = LineChartData(
                color="red",
                stroke_width=2,
                curved=True,
                points=[]
            )
            series_lagged = LineChartData(
                color="blue",
                stroke_width=2,
                curved=True,
                points=[]
            )
            
            # Sync standard check
            if i_data:
                for item in i_data:
                     series_inflow.points.append(
                         LineChartDataPoint(x=float(item['time']), y=item['value'])
                     )
            if l_data:
                for item in l_data:
                     series_lagged.points.append(
                         LineChartDataPoint(x=float(item['time']), y=item['value'])
                     )

            inflow_chart.data_series = [series_inflow, series_lagged]
            
            if series_inflow.points:
                xs = [pt.x for pt in series_inflow.points]
                ys = [pt.y for pt in series_inflow.points] + [pt.y for pt in series_lagged.points]
                inflow_chart.min_x = min(xs)
                inflow_chart.max_x = max(xs)
                min_y = min(ys)
                max_y = max(ys)
                # Padding
                yrange = max_y - min_y
                inflow_chart.min_y = min_y - (yrange * 0.1)
                inflow_chart.max_y = max_y + (yrange * 0.1)

            status_txt.value = f"Updated {len(p_data)} candles"
            page.update()
            
        except Exception as ex:
            import traceback
            traceback.print_exc()
            status_txt.value = f"Error: {ex}"
            page.update()

    # Sidebar
    sidebar = ft.Container(
        width=300,
        bgcolor="#262730",
        padding=20,
        content=ft.Column([
            ft.Text("INFLOW BOT V2", size=20, weight=ft.FontWeight.BOLD, color="red400"),
            ft.Divider(),
            dd_timeframe,
            sb_window,
            sb_days,
            chk_refresh,
            ft.FilledButton("Refresh Now", on_click=refresh_data),
            ft.Container(expand=True),
            status_txt
        ])
    )
    
    # Layout
    # Split view: Top Price, Bottom Inflow
    charts_col = ft.Column(
        [
            ft.Container(content=price_chart, expand=True, bgcolor="#131722", padding=10, border_radius=5),
            ft.Container(content=inflow_chart, expand=True, bgcolor="#131722", padding=10, border_radius=5),
        ],
        expand=True
    )
    
    page.add(
        ft.Row(
            [sidebar, charts_col],
            expand=True,
            spacing=0
        )
    )
    
    # Initial load
    await refresh_data()

if __name__ == "__main__":
    ft.run(target=main)
