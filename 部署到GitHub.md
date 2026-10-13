# 部署到 GitHub（手机随时随地都能打开）

> ## ✅ 已经部署好了
>
> **你的网址：https://realchenchenluo.github.io/daequan/**
>
> - 仓库：https://github.com/realchenchenluo/daequan
> - GitHub **每 2 小时**自动抓一次并更新页面（一天 12 次，最坏情况陈旧 2-3 小时）
> - 手机上打开上面那个网址 → 加到主屏幕，就跟装了个 App 一样
>
> 想立刻刷新：去 https://github.com/realchenchenluo/daequan/actions →
> 选「更新优惠券页面」→ **Run workflow**
>
> ⚠️ **这个页面对所有人公开**（免费账号只能用公开仓库发布 Pages）。
> 页面里只有券码，**不含你的任何个人信息**——我做过检查。但你要知道这件事。
>
> 下面的内容是完整的原理和排查指南，留着以后出问题用。

---

这份文档讲清楚一件事：**怎么让这个工具变成一个网址，你在外面用手机也能打开。**

---

## 先说结论：有两条路，建议都留着

| | 本地服务 | GitHub Pages ✅ 已部署 |
|---|---|---|
| 网址 | `http://192.168.8.109:8788` | `https://realchenchenluo.github.io/daequan/` |
| 手机能用吗 | 能，但**必须和电脑连同一个 WiFi** | 能，**任何地方、任何网络** |
| 需要电脑开着吗 | 需要 | 不需要 |
| 数据新鲜度 | 你点刷新就重抓 | 每 2 小时自动抓一次 |
| 隐私 | 只有你局域网里的人看得到 | **公开的，有链接的人都能看** |
| 美团专属券 | **有**（本机有登录态） | 没有（见第七节） |

**建议**：在家用本地服务（数据最新、券最全），出门用 GitHub（随时能开）。两者不冲突。

---

## 一、为什么不能直接在网页里调接口

你可能会想：既然本地服务能实时抓，那 GitHub Pages 上也让它实时抓不就行了？

**不行。** 有两个原因：

1. **跨域限制**。GitHub Pages 上的网页想直接去请求 `agskills.moontai.top` 这个接口，浏览器会因为跨域（CORS）把它拦下来。
2. **会把第三方接口暴露在每个访客的请求里**，对那个免费接口不公平，也不稳定。

**所以正确做法是**：让 GitHub 自己的服务器定时去抓，抓完生成一个静态页面发布出去。我已经把配置写好了，就在 `.github/workflows/update-coupons.yml`。

---

## 二、隐私这件事，先说清楚

GitHub Pages 有个硬规则：**免费账号只能用「公开仓库」发布 Pages**。也就是说，发布之后：

- 页面是**公开的**，任何拿到网址的人都能看到你抓到的券码
- 仓库也是公开的，代码任何人都能看

**这些券码本身不敏感**——它们本来就是推广渠道公开发的领券口令，谁都能拿到，不含你的任何个人信息。

**但要确认两件事**：

1. **不要在这个仓库里放美团登录凭证。** 工作流里我刻意没启用美团官方直发券（那条需要手机号登录），就是为了不把你的 token 传到 GitHub 上。想领美团大额券，在本机跑 `python run.py 登录` 和 `python run.py 领券`。
2. **`.gitignore` 已经把 `data/` 排除了**，你的登录凭证和历史记录不会被提交。别手贱改它。

如果你连"券码被别人看到"都不想要，那就**只用本地服务**，别走 GitHub。

---

## 三、部署步骤

### 前提：一个我判断错了的地方（留个记录）

我一开始检查你的 gh 登录，看到权限只有 `gist, read:org, repo`，**没有 `workflow`**，就判断推送 `.github/workflows/` 下的文件会被 GitHub 拒绝，让你去跑 `gh auth refresh -s workflow`。

**这个判断是错的。** 实际推送一次就成功了，工作流文件正常上传，GitHub 也把它识别成了 active。

原因大概是：那个 `workflow` 权限限制针对的是用 **API 直接创建/修改**工作流文件的场景；而 `git push` 走的是 git 协议加凭据助手，不受这条限制管。

**结论：你不需要跑任何额外命令。** 已经部署好了。把这段留着，是为了以后再遇到类似问题时，不用重复我这个误判。

### 实际执行的命令（备查）

```bash
cd "D:\Desktop\美团 淘宝闪购优惠券搜寻"

git init
git add -A
git commit -m "优惠猎手：美团 / 淘宝闪购 / 京东 优惠券聚合工具"

git fetch origin main
git merge origin/main --allow-unrelated-histories   # 合并掉建仓时那个自动生成的 README

git branch -M main
git remote add origin https://github.com/realchenchenluo/daequan.git
git push -u origin main

# 开启 Pages，指定用 GitHub Actions 作为构建来源
gh api -X POST repos/realchenchenluo/daequan/pages -f build_type=workflow

# 手动触发第一次构建
gh workflow run update-coupons.yml -R realchenchenluo/daequan
```

> 小坑记录：`git init` 在这台机器上默认建的是 `master` 分支，
> 直接 `git push origin main` 会报 `src refspec main does not match any`。
> 要先 `git branch -M main` 改名。

### 然后是 Pages 配置

推送成功后：

1. 打开 `https://github.com/你的用户名/coupon-hunter/settings/pages`
2. **Source** 选 **GitHub Actions**（不是 "Deploy from a branch"）
3. 去 `Actions` 标签页，找到「更新优惠券页面」，点 **Run workflow** 手动触发一次

等一分钟左右，网址就是：

```
https://你的用户名.github.io/coupon-hunter/
```

⚠️ **一个容易踩的坑**：如果你先推送了代码，但还没把 Pages 的 Source 改成 "GitHub Actions"，第一次部署会失败。改了再跑一次就行。

---

## 四、手机上怎么用

1. 手机浏览器打开你的网址
2. **加到主屏幕**（这一步很关键）：
   - **iPhone**：Safari 底部「分享」→「添加到主屏幕」
   - **安卓**：Chrome 右上角「⋮」→「添加到主屏幕」
3. 之后就像个 App 一样，点图标直接打开

页面是按手机优先做的：吸顶标题、平台筛选、大号复制按钮（超过 44px 触摸目标）、长口令自动换行、适配 iPhone 刘海。

---

## 五、更新频率与手动刷新

工作流**每 2 小时**跑一次（UTC 的偶数点，一天 12 次）。想改频率就编辑
`.github/workflows/update-coupons.yml` 里这一行：

```yaml
- cron: '0 */2 * * *'
```

⚠️ **GitHub 的定时用的是 UTC 时间，不是北京时间**，换算公式：

```
北京时间 - 8 小时 = UTC
例：想在北京时间 09:00 跑 → UTC 01:00 → 写成 '0 1 * * *'
```

### 为什么是每 2 小时这么频繁？

因为 **GitHub 的定时任务不准时**，这是实测到的：

| 计划执行 | 实际执行 | 延迟 |
|---|---|---|
| UTC 11:00 | UTC 20:00 | **晚了 9 小时** |
| UTC 23:00 | UTC 01:52（次日） | 晚了近 3 小时 |

高峰期延迟是 GitHub 定时任务的已知行为，**改配置消除不掉**。所以用"跑得勤"
来对冲——跑 12 次总有一次落在你需要的时间附近，最坏情况页面旧 2-3 小时，
而不是"运气不好就旧 20 小时"。公开仓库跑 Actions 不花钱。

### 想更准时怎么办

| 办法 | 准时程度 | 代价 |
|---|---|---|
| **GitHub 定时**（现在用的） | 差（可能晚几小时） | 无 |
| **Windows 任务计划程序** | **准到分钟** | 要开着电脑 |
| **Cloudflare 定时** | 准到分钟 | 要注册 Cloudflare 并配置 |
| 手动触发 | 立刻 | 每次去点一下 |

**本机定时任务我早就做好了**，一条命令就能装（电脑开着时才生效）：

```bash
python run.py 定时任务 --安装
```

不想要了 `python run.py 定时任务 --卸载`，完全恢复原样。

### 手动立刻刷新

去仓库的 **Actions** 标签页 → 「更新优惠券页面」→ **Run workflow**。

## 六、保活机制（防止定时更新无声无息地停掉）

### 为什么需要它

GitHub 有一条规则：**仓库连续 60 天没有任何提交，所有定时工作流会被自动暂停。**

两个容易踩的坑：

1. **定时任务自己执行不算仓库活动**，只有提交才算。所以"我配了定时任务"这件事本身不能阻止被暂停。
2. **暂停是静默的**，GitHub 不会给你发通知。表现就是某天你打开页面，发现时间不走了。

### 已经做好了，你不用管

`.github/workflows/keepalive.yml` 做了两层保险：

| 层 | 做什么 | 什么时候动 |
|---|---|---|
| 主防线 | 刷新 `.github/keepalive.txt` 并提交，把 60 天计时器清零 | 上次提交超过 **25 天**时 |
| 兜底 | 检查各工作流状态，被停用的自动重新启用 | 每次都检查 |

**阈值为什么是 25 天而不是 55 天**：留足容错。万一某次保活任务自己没跑成（GitHub 也会抽风），还有 35 天余量再试一次，不会直接撞上 60 天红线。

**噪音有多大**：只有超过 25 天没提交才会动作，所以正常情况下**大约每月 1 次提交**。如果你经常改代码，它永远不会触发。

### 想验证它真的能用

它平时什么都不做，所以你没法"看着它工作"。我给了一个手动开关：

去 https://github.com/realchenchenluo/daequan/actions/workflows/keepalive.yml
→ **Run workflow** → 勾上 **force** → 运行

这样会强制走一遍完整流程（真的提交一次），你能从日志里看到全过程。**我已经实测过两条路径**：

```
正常情况：距上次提交 0 天 → 不动任何东西 → 提交无变化  ✓
强制保活：走完整流程 → 产生新提交 → keepalive.txt 时间戳更新  ✓
```

### 不想要它

删掉 `.github/workflows/keepalive.yml` 就行（`.github/keepalive.txt` 也可以一起删）。代价是定时更新会在 60 天后被 GitHub 静默暂停。

---

## 七、本地服务和 GitHub 怎么配合用

两者不冲突，建议这样：

- **在家**：用本地服务 `http://192.168.8.109:8788`。它数据最新（点刷新就重抓），而且**包含美团官方专属券**（因为只有本机有你的登录态）。
- **在外面**：用 GitHub Pages 那个网址。它只有通用口令券，但胜在随时随地能开。

**为什么 GitHub 上没有美团专属券？** 因为领那个券需要你的美团登录 token。把 token 放到公开仓库的 GitHub Actions 里 = 把你的账号交给第三方服务器，**这个我坚决不做**。

---

## 八、不想用了怎么删干净

```bash
# 删掉远程仓库（谨慎，不可恢复）
gh repo delete 你的用户名/coupon-hunter --yes

# 本地停止服务：在服务窗口按 Ctrl+C
```

注意：公开仓库一旦被别人 fork 或者被搜索引擎/存档站抓走，那部分内容就不受你控制了。**所以发布前先想清楚**。

---

## 九、一句话总结

- **本地服务**：已经能用，`本地服务.bat` 双击。手机连同一个 WiFi 就能开，功能最全。
- **GitHub Pages**：**已经部署好了**，不需要你做任何事。地址是 https://realchenchenluo.github.io/daequan/ ，每 2 小时自动更新。
- **保活**：已经配好，不用管。它保证定时更新不会在 60 天后被 GitHub 静默暂停。
