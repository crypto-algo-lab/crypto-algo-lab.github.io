---
layout: post
title: "[hybrid_boost_trader] トレンドフィルター 4h→2h EMA200 変更"
date: 2026-05-01
notion_id: 3578f0b7-804f-81e7-8822-f52bc392302a
categories: [レポート]
tags: [EMA200, トレンドフィルター, Python]
excerpt: "hybrid_boost_traderのトレンドフィルター足種を4時間足から2時間足EMA200に変更した実装ログ。"
header:
  teaser: /assets/images/thumb-trend-timing.png
  overlay_image: /assets/images/thumb-trend-timing.png
  overlay_filter: 0.3
---

実装変更の記録としてログを残しておく。

## 変更内容

- **変更前**: `trend_timeframe = "4h"` でEMA200を計算してトレンド判定
- **変更後**: `trend_timeframe = "2h"` に変更

変更箇所は設定ファイルの1パラメータのみ。

## 変更理由

4時間足でのトレンド判定が遅く、実際の相場の転換点に対して反応が遅れるケースがあった。
バックテストで足種を複数比較した結果、2時間足が最良の損益を示したため採用。

![トレンドフィルター 足種別損益比較]({{ '/assets/images/trend-filter-pnl.png' | relative_url }})

## 動作確認

変更後の挙動：
- EMA200（2時間足）が上向きのときのみロングエントリーを許可
- それ以外はシグナルが出てもスキップ

本番環境でも問題なく動作していることを確認済み。
