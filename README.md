# reminder_cross_trading

18:50になったらremindを流してくれるDiscord Botです．

## 動作

- `/remind-on` と `/remind-off` は、リマインド全体のON/OFFスイッチです。
- ONの場合でも、通常は送信しません。
- Gokigen Lifeの優待クロスカレンダーで「SBIフライング」日程を検出した日から、次の週末直前の金曜日まで、平日18:50にリマインドを送信します。
- 二重送信防止とON/OFF状態はSupabase側で管理します。

## Supabase

`bot_status` の `id=1` は既存どおりON/OFFと最終送信日の管理に使います。

自動送信期間の終了日は、同じ `bot_status` の `id=2` の `last_sent_at` に保存します。
