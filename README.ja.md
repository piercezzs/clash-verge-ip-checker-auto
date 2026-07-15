# Clash Verge IP Checker Auto

[English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md)

Clash Verge Rev 向けのローカルノード整理ツールです。ローカルプロファイルを読み取り、ノードの出口 IP 品質を検査し、新しい checked YAML を出力して、その結果を Clash Verge に戻すためのインポートリンクを生成します。

これは [tombcato/clash-ip-checker](https://github.com/tombcato/clash-ip-checker) をもとにした個人向け改造版です。Clash Verge Rev で自分が使いやすいように、ローカル設定の自動読み取り、エクスポート前の高リスクノード除外、最後の手動有効化を中心に調整しています。

自分の端末、または信頼できる LAN 内で使う前提です。公開インターネットには出さないでください。

## 元プロジェクトとの主な差分

- Clash Verge Rev のローカル設定を直接読み取り、サブスクリプション YAML を画面に貼り付ける必要がありません。
- Clash Verge Rev のデータディレクトリ、`profiles.yaml`、サブスクリプション YAML、External Controller address、ローカル secret を自動検出します。
- 検査できる Remote / Local のメインプロファイルだけをデフォルト表示し、Merge、script、rules などは別枠で折りたたみます。
- IPPure 高速チェックは元プロジェクトの検査端を使わず、Ping0/Fallback も有効化していません。
- 新しい checked YAML を出力しますが、元のサブスクリプションを上書きせず、`profiles.yaml` を編集せず、現在のサブスクリプションを自動で置き換えません。
- モバイル向けサブスクリプション URL/QR コードは LAN 起動モードでのみ生成します。出力済み YAML の取り込み用であり、サービス起動用ではありません。
- LAN モードは信頼できる端末がこのコンピューターの出力 YAML をダウンロードするためのものです。ログイン層はなく、公開ホスティング向けではありません。
- 検査結果を SQLite `data/results.sqlite3` に保存し、プロファイルとノード内容ごとに最近の結果を再利用できます。
- 検査完了済みでリスクスコアが 30% 以下のノードだけをデフォルト選択します。Pending、失敗、不明、高リスクのノードは選択しません。
- 出口 IP で重複排除し、出力済みファイル一覧も残して、重複ノードと手動選別を減らします。

## 機能

- Clash Verge Rev の `profiles.yaml` と `profiles/` 配下の YAML ファイルを読み取ります。
- ノード検査中に Clash External Controller 経由でモードと選択中のプロキシを一時的に切り替えます。
- デフォルトでは IPPure の高速チェックでノードの出口 IP 品質を検査します。
- 必要に応じて、より遅いが情報量の多いブラウザベースの IPPure チェックも利用できます。
- ローカルの `exports/` に新しい `*_checked.yaml` を出力します。
- `clash://install-config` インポートリンクを生成します。LAN 起動モードでは、出力済み YAML を取り込むためのモバイル向けサブスクリプション URL/QR コードも生成します。

## 安全上の境界

- 既存の Clash Verge プロファイルファイルは上書きしません。
- `profiles.yaml` を直接編集しません。
- Clash Verge の内部 Tauri IPC は呼び出しません。
- 現在のサブスクリプションを自動で置き換えたり、有効化したりしません。
- インポートされた checked サブスクリプションは、Clash Verge 側でユーザーが手動で確認し、有効化する必要があります。
- 検査中は Clash External Controller を使って Clash のモードと選択ノードを一時的に変更します。検査終了後、ツールは元のモードへ戻すよう試みます。
- 現在使用中ではないプロファイルを一時ロードして検査する場合、Clash core 設定を一時的に reload し、その後ランタイム設定を復元するよう試みます。

最後の有効化は Clash Verge 側で手動確認してください。サブスクリプションの有効化や置き換えは実際の通信経路を変えるため、このツールでは自動実行しません。

## 必要条件

- Python 3.10+。
- Clash Verge Rev がインストール済みであること。
- 検査中は Clash Verge Rev が起動していること。
- Clash Verge Rev の External Controller が有効であること。
- 選択するプロファイルは、ローカル YAML に裏付けられた Remote または Local のメインプロファイルであること。

## Clash Verge Rev の準備

1. Clash Verge Rev を開きます。
2. 設定ページを開きます。
3. Clash/Mihomo core 設定エリアを探します。
4. 使用中のバージョンに External Controller または HTTP controller のスイッチがある場合は有効にします。
5. 可能であれば controller は localhost にバインドしてください。例: `127.0.0.1:9097`。
6. controller に secret を設定している場合は、ローカルに保持してください。GitHub issue、チャット、スクリーンショット、公開ログに secret を貼り付けないでください。

Clash Verge Rev のバージョンによって UI ラベルは異なります。ローカルの `config.yaml` に `external-controller` が存在する場合、このツールはその値を自動的に読み取ります。

API secret 入力欄はフォールバック用です。ローカルの Clash Verge 設定に secret がある場合、バックエンドがそれを読み取り、画面には表示しません。

## クイックスタート

### macOS

```bash
./run_mac.command
```

このスクリプトは必要に応じて `.venv` を作成し、依存関係をインストールし、ローカル Web UI を起動して次の URL を開きます。

```text
http://127.0.0.1:8080
```

### Windows

```bat
run_windows.bat
```

このスクリプトは必要に応じて `.venv` を作成し、依存関係をインストールし、ローカル Web UI を起動して次の URL を開きます。

```text
http://127.0.0.1:8080
```

### 手動起動

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python web.py
```

開く URL:

```text
http://127.0.0.1:8080
```

ブラウザベースの検査を使う場合は、Playwright の Chromium ランタイムをインストールしてください。

```bash
.venv/bin/python -m playwright install chromium
```

高速モードでは Playwright Chromium の起動は不要です。

## 基本的な流れ

1. Clash Verge Rev を起動します。
2. External Controller が有効であることを確認します。
3. このツールを起動します。
4. 対応している Remote または Local のメインプロファイルを選びます。
5. まず `proxy group` は `auto` のままにします。
6. `Check current content` をクリックします。
7. proxy group の自動検出に失敗した場合は、実際の Clash proxy group 名を入力します。例: `GLOBAL`、`Proxy`、`PROXY`、またはプロファイルで使用している selector 名。
8. checked ノード一覧と選択済みノードを確認します。
9. `Export selected` をクリックします。
10. エクスポートダイアログで、生成された YAML をダウンロード、コピー、またはインポートします。
11. インポート後、使用したい場合は Clash Verge を開き、新しい checked サブスクリプションを手動で選択または有効化します。

モバイル向けサブスクリプション URL/QR コードは LAN 起動モードでのみ生成します。通常の localhost 起動では、モバイル端末で使える QR コードは出ません。モバイル端末はこのコンピューターが出力した YAML を取り込むだけで、このツール自体は起動しません。

Remote プロファイルの場合、`Refresh source and check` は最新のリモート YAML をメモリ上に取得して検査し、checked YAML を出力します。元のサブスクリプションファイルには書き戻しません。

## LAN アクセス

LAN モードは、同じ信頼できるネットワーク上の端末から、このコンピューターの checker UI を開く、または生成された YAML をダウンロードする場合だけ使ってください。

macOS:

```bash
./run_lan_mac.command
```

Windows:

```bat
run_lan_windows.bat
```

LAN モードでは Web サーバーを `0.0.0.0` にバインドし、現在の LAN IP を検出しようとします。例:

```text
http://192.168.1.23:8080
```

自動検出されたアドレスが違う場合は、起動前に手動で設定できます。

```bash
CLASH_CHECKER_PUBLIC_BASE_URL=http://192.168.1.23:8080 ./run_lan_mac.command
```

重要な LAN 境界:

- LAN ページが操作するのは、このコンピューター上で動いているサービスです。
- ツールが読み取るのはこのコンピューターの Clash Verge ファイルであり、制御するのもこのコンピューターの Clash External Controller です。
- 他の人があなたの LAN ページを使って、自分のコンピューター上の Clash Verge を読み取ったり制御したりすることはできません。
- 別の端末の Clash Verge を処理したい場合は、その端末でこのツールをローカル実行してください。
- このサービスを公開インターネットに晒さないでください。ログイン層はありません。
- macOS または Windows Firewall が Python のネットワークアクセスを求めた場合、信頼できる LAN でのみ許可してください。

## ローカルデータとプライバシー

このツールはローカルの Clash Verge profile メタデータと profile YAML 内容を読み取ります。生成データはデフォルトでローカルに保存されます。

- 出力された YAML は `exports/` に書き込まれます。
- 検査キャッシュと結果は `data/results.sqlite3` に保存されます。
- 一時ランタイムファイルは `.runtime/` に書き込まれる場合があります。

このリポジトリでは以下のパスを Git ignore しています。

```gitignore
exports/
data/
.runtime/
.venv/
```

公開または fork を push する前に、次を実行してください。

```bash
git status --short --ignored
git ls-files exports data .runtime
```

期待される結果: 生成された exports、ローカル SQLite データベース、一時ランタイムファイルは ignored になり、`git ls-files` には表示されません。

コミットしてはいけないもの:

- Clash Verge の `profiles.yaml`。
- 実際のプロバイダーから取得したサブスクリプション YAML。
- 出力された checked YAML。
- `data/results.sqlite3`。
- API secret、プロバイダー URL、token、またはサブスクリプション名や URL が見えるスクリーンショット。

## ライセンスと帰属

このリポジトリは GPL-3.0 を継承しています。詳細は [LICENSE](LICENSE) を参照してください。

コードは [tombcato/clash-ip-checker](https://github.com/tombcato/clash-ip-checker) をもとに改造しています。元の作者およびコントリビューターは元の貢献部分の著作権を保持し、このリポジトリ内の追加変更はこのリポジトリで保守します。

これは上流の公式リリースではありません。帰属情報は [NOTICE](NOTICE) を参照してください。

## UI メモ

- サブスクリプション一覧は、デフォルトでは選択可能な Remote と Local のメインプロファイルのみを表示します。
- Merge、script、rules などの未対応フラグメントは、完全なノードサブスクリプションではないため、折りたたみセクションに表示されます。
- 高速チェックモードは IPPure HTTP lookup を使用し、推奨されるデフォルトです。
- 高速チェックをオフにするとブラウザベースの checker を使います。遅くなりますが、bot-score 系の情報を収集できます。
- エクスポート選択は、完了済みのリスクスコアが 30% 以下のノードをデフォルトで選択します。
- Pending、失敗、不明、リスクが 30% を超えるノードはデフォルトでは選択されません。
- 表示されるノード一覧は、具体的な出口 IP によって重複排除されます。空、pending、unknown、N/A の IP 値は重複排除対象外です。

## トラブルシューティング

### プロファイルが見つからない

- Clash Verge Rev がインストールされていることを確認してください。
- Clash Verge Rev を少なくとも一度開いていることを確認してください。
- データディレクトリをカスタムしている場合は、UI に入力するか、`CLASH_VERGE_HOME` を設定してください。

### Clash External Controller に接続できない

- Clash Verge Rev を起動してください。
- Clash Verge Rev 設定で External Controller または HTTP controller を有効にしてください。
- このツールに表示されている controller address が Clash 設定と一致していることを確認してください。
- secret が設定されている場合は、ツールにローカルで読み取らせるか、API secret 入力欄に入力してください。

### proxy group の自動検出に失敗する

selector/proxy group 名を手動で入力してください。この group は、検査中に Clash が各ノードへ切り替えられる group である必要があります。

### インポートしたサブスクリプションが有効にならない

これは想定された挙動です。インポートは新しい checked サブスクリプションを作成しますが、Clash Verge が自動で選択するとは限りません。Clash Verge を開き、確認したうえで checked サブスクリプションを手動で選択または有効化してください。
