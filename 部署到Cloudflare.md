# 部署到 Cloudflare（可选）

**先看结论，再决定要不要折腾。**

---

## 一、能部署吗？能。但你可能想要的和它擅长的不是一回事

| | GitHub Pages（你现在用的） | Cloudflare Pages |
|---|---|---|
| 能不能部署 | ✅ 已部署 | ✅ 可以，我配置都写好了 |
| 免费 | ✅ | ✅ |
| **国内无代理能不能开** | 时好时坏 | **据我所知更差**（见下节） |
| 数据实时性 | ❌ 只能定时抓（12 小时一次） | ✅ **能做到实时**（靠 Functions） |
| 自动更新 | ✅ 已配 | ✅ 已配（同一个定时） |

**如果你想要的是"更多人能打开"——Cloudflare 帮不上忙，很可能更糟。**
**如果你想要的是"数据实时刷新"——Cloudflare 能做到，这是它真正比 GitHub 强的地方。**

---

## 二、一个你必须先知道的事实：你现在能打开，是因为走代理

我在你这台机器上查了一下：

```
系统代理: 127.0.0.1:7890（7890/7891 都在监听）
域名解析: github.io  → 198.18.0.53
          pages.dev  → 198.18.0.139
```

`198.18.0.0/15` 是**代理软件的「假 IP」段**（TUN + fake-IP 模式）。也就是说：

> **你测出来的"能打开"，全都是经过代理的结果，不代表别人不挂代理也能打开。**

这一点我一开始没意识到，差点给你错误的结论。

### 那没有代理的人能不能打开？

**我测不了**——代理是 TUN 模式，接管所有流量，从这台机器上绕不过去。所以下面是我的了解，**不是实测，请按"默认不可信"对待**：

| 域名 | 我的了解 | 可信度 |
|---|---|---|
| `*.github.io` | 国内时好时坏 | 低（没见过权威数据） |
| `*.pages.dev` | 据我所知国内明确不可达（DNS 污染 + SNI 阻断） | 中 |
| `*.workers.dev` | 同上 | 中 |

**所以你如果打算把链接发给国内的朋友，两个默认域名都不能保证。**

### 真想稳，唯一的办法是自定义域名

不管挂在哪家，**绑一个自己的域名**才是可靠的。原因：域名被墙的是 `pages.dev` / `github.io` 这些**共享域名**，你自己的域名通常不在名单里。

成本：域名一年大概 ¥30–60。这是唯一能实质改善可达性的办法，Cloudflare 本身解决不了这个。

---

## 三、Cloudflare 真正值钱的地方：Functions（能拿实时数据）

GitHub Pages 是**纯静态托管**，所以数据只能靠定时任务预先抓、12 小时才更新一次。

Cloudflare 有 **Functions**（跑在服务端的函数），可以在**每次有人打开页面时**去抓一次最新数据。这样页面永远是新的，也不会有跨域问题（因为是服务端抓的）。

**代价**：那需要把渲染逻辑用 JavaScript 再写一遍（Cloudflare 跑不了这个 Python 项目），而且**我没法替你测**（需要你的 Cloudflare 账号）。等于多一份要维护的代码。

**我的建议**：先别做。你现在缺的不是"更实时"，而是"别人能打开"。真要解决后者，自定义域名比换平台有用得多。

---

## 四、想启用 Cloudflare Pages（三步）

配置我已经写好了：`.github/workflows/deploy-cloudflare.yml`。**没配密钥时它会自动跳过，不会报错。**

### 第 1 步：在 Cloudflare 建项目

1. 注册 https://dash.cloudflare.com （免费）
2. 左侧 **Workers & Pages** → **Create** → **Pages** → **Upload assets**
3. 项目名填 **`daequan`**（必须和配置文件里的一致）
4. 先随便传个文件建好项目就行，后面 GitHub 会自动推

### 第 2 步：拿两个值

| 要什么 | 去哪拿 |
|---|---|
| **Account ID** | Cloudflare 首页右侧栏，或 Workers & Pages 页面右侧 |
| **API Token** | 右上角头像 → My Profile → API Tokens → Create Token → 用 **Edit Cloudflare Workers** 模板 |

### 第 3 步：填进 GitHub

打开 https://github.com/realchenchenluo/daequan/settings/secrets/actions
→ **New repository secret**，加两个：

```
CLOUDFLARE_API_TOKEN   = 刚才拿到的 token
CLOUDFLARE_ACCOUNT_ID  = 刚才拿到的 Account ID
```

加完去 https://github.com/realchenchenluo/daequan/actions
→ 选「同步到 Cloudflare Pages」→ **Run workflow**

跑成功后你的 Cloudflare 地址是：

```
https://daequan.pages.dev
```

---

## 五、一句话总结

- **能部署**，配置我已经写好了，你按上面三步走就能上线
- **但默认域名 `pages.dev` 在国内据我所知是打不开的**（这条我没法在你这台机器上实测，因为代理接管了流量）
- **你现在能打开 github.io，是因为你挂着代理** —— 别人可能打不开
- 想真正解决"别人也能打开"，**自定义域名**比换平台有效得多
- Cloudflare 真正的优势是 **Functions 能拿实时数据**，但那要重写一份 JS 代码，而且我测不了，建议先不做

**我的建议**：除非你明确想要"实时数据"，否则这个先不做。真要让链接能发出去，去买个域名绑到 GitHub Pages 上更直接。
