# GFWList formats / GFWList 多种格式

Source: [gfwlist/gfwlist](https://github.com/gfwlist/gfwlist), commit
`4238995aba9dddd7d9f3e6821cd43bad9b87523d` (2026-10-17).
The original list and its conversions are distributed under the upstream
LGPL-2.1 license in [COPYING.txt](COPYING.txt). This is a pinned snapshot;
it does not update automatically.

来源：[gfwlist/gfwlist](https://github.com/gfwlist/gfwlist)，提交
`4238995aba9dddd7d9f3e6821cd43bad9b87523d`（2026-10-17）。
原列表和转换结果遵循上游 LGPL-2.1 许可，见 [COPYING.txt](COPYING.txt)。
这是固定版本，不会自动更新。

| File / 文件 | Use / 用途 |
| --- | --- |
| [gfwlist.txt](gfwlist.txt) | Original Base64 AutoProxy list / 上游 Base64 原文件 |
| [list.txt](list.txt) | Decoded AutoProxy rules, with the original syntax / 解码后的完整 AutoProxy 规则 |
| [domains.txt](domains.txt) | Plain domain suffixes, one per line / 每行一个域名后缀；不含排除规则 |
| [local-domains.txt](local-domains.txt) | Local additions to the converted formats / 转换结果的自定义补充域名 |
| [exceptions.txt](exceptions.txt) | Convertible domain exceptions / 可转换的域名例外规则 |
| [unsupported.txt](unsupported.txt) | Rules that cannot safely become domain suffixes / 无法安全转换成域名后缀的规则 |
| [sing-box.json](sing-box.json) | sing-box source rule set / sing-box 源规则集 |
| [sing-box.srs](sing-box.srs) | Compiled sing-box binary rule set / sing-box 二进制规则集 |

The sing-box files contain **4,093 upstream domain suffix rules, one local
addition (`speedtest.net`), and 31 domain exceptions**. The original
`gfwlist.txt` and decoded `list.txt` are unchanged upstream snapshots and do
not include the local addition. The converted files omit **289 URL, wildcard,
regular-expression, and other rules** listed in `unsupported.txt`. Thus they
approximate, rather than fully reproduce, GFWList. `domains.txt` does not
apply the exceptions; use the sing-box files for the Mac profile in this
repository.

sing-box 文件包含 **4,093 条上游域名后缀规则、1 条自定义规则
（`speedtest.net`），以及 31 条域名例外规则**。原始 `gfwlist.txt` 和
解码后的 `list.txt` 保持上游内容，不包含这条自定义规则。
`unsupported.txt` 另列出 **289 条网址路径、通配符、正则等规则**，这些规则未被转换。
因此 sing-box 版本只是 GFWList 的域名规则转换版，不能完全复现原列表。
`domains.txt` 不处理例外规则；本仓库的 Mac 配置应使用 `.srs` 文件。

如果首次启动时无法下载 `.srs`，可使用仓库根目录的
[mac.offline.example.json](../mac.offline.example.json)。它内嵌本页的规则，
无需首次下载，但不会自动更新。

To use this repository's binary rule set, replace
`REPLACE_WITH_YOUR_GFWLIST_SRS_URL` in your private `mac.json` with:

```text
https://raw.githubusercontent.com/qudy2001/cloudflare-sing-box/main/proxylist/sing-box.srs
```

如需使用此仓库的二进制规则集，在自己的 `mac.json` 中将
`REPLACE_WITH_YOUR_GFWLIST_SRS_URL` 替换成上述地址。客户端需要能够访问该地址。

To regenerate from a downloaded upstream `gfwlist.txt`, run from the
repository root:

```sh
python3 scripts/build_proxylist.py /path/to/gfwlist.txt proxylist \
  --extra-domains proxylist/local-domains.txt
docker run --rm -v "$PWD/proxylist:/rules" ghcr.io/sagernet/sing-box:v1.14.3 \
  rule-set compile --output /rules/sing-box.srs /rules/sing-box.json
```

更新时先下载新的上游 `gfwlist.txt`，执行上述命令，核对
`unsupported.txt`、上游许可和本页的提交号与统计数字，再提交文件。
