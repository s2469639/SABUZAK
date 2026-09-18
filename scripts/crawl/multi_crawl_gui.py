#!/usr/bin/env python3
"""
tradefairdates.com 다중 카테고리 통합 크롤러 (GUI 버전)

- 7개 카테고리 URL을 한 번에 크롤링
- 전체 결과에서 중복(같은 전시회가 여러 카테고리에 겹쳐 나오는 경우) 제거
- 버튼 하나로 실행되는 간단한 창(GUI) 제공

사전 준비:
    pip install requests beautifulsoup4
    (tkinter는 표준 파이썬에 기본 포함되어 있어 별도 설치 불필요)

실행:
    python multi_crawl_gui.py

주의:
    이 파일은 반드시 tradefairdates_scraper.py 와 같은 폴더에 있어야 합니다.
    (그 파일 안의 크롤링 함수들을 그대로 가져다 씁니다)
"""

import csv
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import requests

# 같은 폴더의 tradefairdates_scraper.py 를 모듈로 불러와 재사용
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tradefairdates_scraper as tfd

SITES = [
    ("Bakery Trade Shows", "https://www.tradefairdates.com/Bakery-Trade-Shows-Y36-S1.html"),
    ("Speciality Fine Food Fairs", "https://www.tradefairdates.com/Speciality-Fine-Food-Fairs-Y108-S1.html"),
    ("Fancy Food Shows", "https://www.tradefairdates.com/Fancy-Food-Shows-Y82-S1.html"),
    ("Trade fair for Seafood", "https://www.tradefairdates.com/Trade-fair-for-Seafood-Y417-S1.html"),
    ("Trade Fairs for Beer", "https://www.tradefairdates.com/Trade-Fairs-for-Beer-Y414-S1.html"),
    ("Food Trade Shows", "https://www.tradefairdates.com/Food-Trade-Shows-Y256-S1.html"),
    ("Food Fairs", "https://www.tradefairdates.com/Food-Fairs-Y216-S1.html"),
]

FIELDNAMES = ["출처카테고리"] + tfd.FIELDNAMES


def row_key(row):
    return row.get("_detail_url") or (
        row["전시회명"], row["시작일"], row["종료일"], row["개최장소(베뉴)"]
    )


def crawl_all_sites(selected_sites, with_details, log, should_stop):
    """selected_sites: [(label, url), ...] / log: 콜백 함수 / should_stop: 취소 확인 함수"""
    all_rows = []
    seen_keys = set()

    for label, url in selected_sites:
        if should_stop():
            log(f"중단됨.")
            break

        log(f"\n=== [{label}] 크롤링 시작 ===")
        try:
            rows = tfd.crawl_all_pages(url)
        except requests.exceptions.RequestException as e:
            log(f"  -> 실패: {e}")
            continue

        new_rows = []
        dup_count = 0
        for r in rows:
            key = row_key(r)
            if key in seen_keys:
                dup_count += 1
                continue
            seen_keys.add(key)
            r["출처카테고리"] = label
            new_rows.append(r)

        log(f"  -> {label}: 총 {len(rows)}건, 중복 제외 {dup_count}건, 신규 {len(new_rows)}건")
        all_rows.extend(new_rows)

    if with_details and not should_stop():
        log(f"\n=== 상세페이지(축제URL/소개) 수집 시작: 총 {len(all_rows)}건 ===")
        total = len(all_rows)
        for i, row in enumerate(all_rows, 1):
            if should_stop():
                log("중단됨.")
                break
            detail_url = row.get("_detail_url", "")
            if not detail_url:
                continue
            log(f"  [{i}/{total}] {row['전시회명']}")
            try:
                detail = tfd.parse_detail(detail_url)
                row["축제URL"] = detail["축제URL"]
                row["축제소개"] = detail["축제소개"]
            except requests.exceptions.RequestException as e:
                log(f"    -> 실패: {e}")
            tfd.polite_sleep()

    return all_rows


def save_csv(rows, out_path):
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in FIELDNAMES})


class App:
    def __init__(self, root):
        self.root = root
        root.title("tradefairdates.com 통합 크롤러")
        root.geometry("720x600")

        self.log_queue = queue.Queue()
        self.worker_thread = None
        self.stop_flag = threading.Event()

        # --- 사이트 선택 체크박스 ---
        site_frame = ttk.LabelFrame(root, text="크롤링할 카테고리 선택")
        site_frame.pack(fill="x", padx=10, pady=8)

        self.site_vars = []
        for label, url in SITES:
            var = tk.BooleanVar(value=True)
            cb = ttk.Checkbutton(site_frame, text=label, variable=var)
            cb.pack(anchor="w", padx=8, pady=2)
            self.site_vars.append((var, label, url))

        # --- 옵션 ---
        option_frame = ttk.Frame(root)
        option_frame.pack(fill="x", padx=10, pady=4)

        self.details_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            option_frame,
            text="상세페이지 정보(축제URL, 한줄소개)도 함께 수집 (시간이 더 걸립니다)",
            variable=self.details_var,
        ).pack(anchor="w")

        # --- 저장 경로 ---
        path_frame = ttk.Frame(root)
        path_frame.pack(fill="x", padx=10, pady=4)

        ttk.Label(path_frame, text="저장할 CSV 파일:").pack(side="left")
        self.out_path_var = tk.StringVar(
            value=os.path.join(os.getcwd(), "tradefairdates_all.csv")
        )
        ttk.Entry(path_frame, textvariable=self.out_path_var, width=50).pack(
            side="left", padx=5, fill="x", expand=True
        )
        ttk.Button(path_frame, text="찾아보기", command=self.browse_path).pack(side="left")

        # --- 버튼 ---
        btn_frame = ttk.Frame(root)
        btn_frame.pack(fill="x", padx=10, pady=8)

        self.start_btn = ttk.Button(btn_frame, text="크롤링 시작", command=self.start_crawl)
        self.start_btn.pack(side="left", padx=4)

        self.stop_btn = ttk.Button(
            btn_frame, text="중단", command=self.stop_crawl, state="disabled"
        )
        self.stop_btn.pack(side="left", padx=4)

        # --- 로그 ---
        log_frame = ttk.LabelFrame(root, text="진행 로그")
        log_frame.pack(fill="both", expand=True, padx=10, pady=8)

        self.log_text = tk.Text(log_frame, wrap="word", state="disabled")
        self.log_text.pack(fill="both", expand=True, side="left")
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        scrollbar.pack(side="right", fill="y")
        self.log_text.config(yscrollcommand=scrollbar.set)

        self.root.after(200, self.poll_log_queue)

    def browse_path(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV 파일", "*.csv")],
            initialfile="tradefairdates_all.csv",
        )
        if path:
            self.out_path_var.set(path)

    def log(self, msg):
        self.log_queue.put(msg)

    def poll_log_queue(self):
        while True:
            try:
                msg = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self.log_text.config(state="normal")
            self.log_text.insert("end", msg + "\n")
            self.log_text.see("end")
            self.log_text.config(state="disabled")
        self.root.after(200, self.poll_log_queue)

    def start_crawl(self):
        selected = [(label, url) for var, label, url in self.site_vars if var.get()]
        if not selected:
            messagebox.showwarning("알림", "최소 1개 카테고리를 선택하세요.")
            return

        out_path = self.out_path_var.get().strip()
        if not out_path:
            messagebox.showwarning("알림", "저장할 CSV 경로를 입력하세요.")
            return

        self.stop_flag.clear()
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")

        def worker():
            try:
                rows = crawl_all_sites(
                    selected,
                    self.details_var.get(),
                    self.log,
                    self.stop_flag.is_set,
                )
                save_csv(rows, out_path)
                self.log(f"\n완료! 총 {len(rows)}건 저장 -> {out_path}")
            except Exception as e:
                self.log(f"\n오류 발생: {e}")
            finally:
                self.log_queue.put("__DONE__")

        self.worker_thread = threading.Thread(target=worker, daemon=True)
        self.worker_thread.start()
        self.root.after(300, self.check_done)

    def check_done(self):
        # 큐에 __DONE__ 마커가 오면 버튼 상태 복구
        temp = []
        done = False
        while True:
            try:
                msg = self.log_queue.get_nowait()
            except queue.Empty:
                break
            if msg == "__DONE__":
                done = True
            else:
                temp.append(msg)
        for msg in temp:
            self.log_queue.put(msg)

        if done:
            self.start_btn.config(state="normal")
            self.stop_btn.config(state="disabled")
        else:
            self.root.after(300, self.check_done)

    def stop_crawl(self):
        self.stop_flag.set()
        self.log("중단 요청됨. 현재 진행 중인 페이지까지만 마치고 멈춥니다...")


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
