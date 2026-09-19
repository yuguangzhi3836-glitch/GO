# 敖麓谷雅历史图片归档恢复核验（2026-09-19）

已从 2026-09-05 的三份归档中实际读到图片字节，不是仅找回图片链接。逐文件重新计算 SHA-256，并用 Pillow 校验和完整解码；全程未解压执行脚本、未访问线上酒店、未修改或发布酒店。

## 可恢复资产

|归档|实际图片文件|独立 SHA-256|完整解码通过|尺寸及现有上传格式通过|
|---|---:|---:|---:|---:|
|GO_AOLUGUYA_8_FAMILY_FINAL_TARGETED_MEDIA_FETCH_HK_20260905.tar.gz|30|30|30|27|
|GO_AOLUGUYA_MEDIA_TRUTH_R2_STRICT_BINDING_20260905.tar.gz|21|21|21|21|
|GO_AOLUGUYA_REAL_MEDIA_READONLY_EXPORT_HK_20260905.tar.gz|199|199|199|42|

尺寸标准为短边至少 720、长边至少 1280；现有直接上传支持 JPEG/PNG/WebP。三包合计 **229 个不重复图片字节对象**，其中 73 个达到尺寸要求，69 个同时符合现有上传格式。严格筛选包的 21 张全部已存在于 199 张原始包中，不能重复计数。目标采集包另有 30 张，27 张达到尺寸要求。

**找回 199 张文件，不等于找回 199 张可用的敖麓谷雅图片。** 原始清单包含其他酒店和泛用素材。21 张严格筛选候选，其归档来源 URL 的 Hyatt 域名、HRBUB 编号与实际文件哈希相符；这证明档案内部一致性，不是当下来源重新核实或发布授权。

目标采集清单有 36 条记录：30 条有完整文件，另 6 条仅是重复引用记录。已核对选中 30 条记录的实际字节哈希和大小；未把 6 条重复引用算作新文件。

## 17 个历史房型候选

|历史编号|历史名称|归档媒体家族|实际引用图片|达到尺寸及格式要求|
|---|---|---|---:|---:|
|SUN_KING|撮罗子·映日大床房|FAMILY_DREAMWEAVER_KING|4|4|
|ROUND_DREAM_KING|撮罗子·圆梦大床房|FAMILY_DREAMWEAVER_KING|4|4|
|WATER_KING|撮罗子·乐水大床房|FAMILY_DREAMWEAVER_KING|4|4|
|SUN_TWIN|撮罗子·映日双床房|FAMILY_DREAMWEAVER_TWIN|3|3|
|ROUND_DREAM_TWIN|撮罗子·圆梦双床房|FAMILY_DREAMWEAVER_TWIN|3|3|
|WATER_TWIN|撮罗子·乐水双床房|FAMILY_DREAMWEAVER_TWIN|3|3|
|PILLOW_MOON_KING|撮罗子·枕月大床房|FAMILY_CLOUDSPIRE_KING|5|4|
|SLEEPING_CLOUD_KING|撮罗子·卧云大床房|FAMILY_CLOUDSPIRE_KING|5|4|
|RIVER_KING|撮罗子·阅江大床房|FAMILY_CLOUDSPIRE_KING|5|4|
|PILLOW_MOON_TWIN|撮罗子·枕月双床房|FAMILY_CLOUDSPIRE_TWIN|5|4|
|SLEEPING_CLOUD_TWIN|撮罗子·卧云双床房|FAMILY_CLOUDSPIRE_TWIN|5|4|
|RIVER_TWIN|撮罗子·阅江双床房|FAMILY_CLOUDSPIRE_TWIN|5|4|
|SUNSET_KING|撮罗子·栖霞大床房|FAMILY_SUNSET_KING|3|3|
|STAR_FAMILY_SUITE|撮罗子·牵星家庭套房|FAMILY_STAR_FAMILY_SUITE|3|2|
|MOON_SUITE|撮罗子·抱月套房|FAMILY_LUAR_EBRACE_SUITE|3|3|
|RAINBOW_FAMILY_SUITE|撮罗子·握虹家庭套房|FAMILY_LUAR_EBRACE_SUITE|3|3|
|PUYUE_SUITE|撮罗子·朴悦套房|FAMILY_MARIA_SUO_SUITE|4|4|

这些是归档的 17 个销售房型编号，归并到 8 个共享图片家族。不能据此认定当前 GO 的 17 个物理房型、也不能自动映射当前携程 19 个来源条目。仍须与当前正式酒店、供应商房型和登记记录逐项对照。

两份历史归档还有编号不一致，尚未自动合并：

|相同历史房型名称|严格筛选包编号|后续目标采集包编号|
|---|---|---|
|撮罗子·牵星家庭套房|STARDUST_FAMILY_SUITE|STAR_FAMILY_SUITE|
|撮罗子·抱月套房|MOON_EMBRACE_SUITE|MOON_SUITE|

目标包中三张图片未达当前尺寸要求：卧云大床媒体家族第 1 张 1152×1024；卧云双床第 1 张 1131×1024；牵星家庭套房第 1 张 1024×683。牵星家族剩 2 张达标，需要补图才能满足历史“至少 3 张”的目标；其余家族仍各有至少 3 张达标候选。未放大、未用截图替代。

## 授权及来源证据边界

原始 199 条记录的历史授权状态为 190 条 RIGHTS_UNKNOWN、9 条 HOTEL_SUBMITTED_INFERRED；后者虽带历史 publishable=true 和审核字段，属于推断标签，不能直接升级为本轮当前授权。没有把归档 PASS 或历史审核人字段当作新发布许可。

目标包保存了来源产品页 URL、抓取日期、页面 SHA 声明、来源房型编号及图片顺序，但未包含来源页面 HTML 原件，因此本轮没有重新证明页面实际摆放关系。历史抓取日期为 2026-09-05，不代表 2026-09-19 在售情况。

## 可以继续做的具体工作

1. 以 21 张 Hyatt 候选和 27 张尺寸合格的目标采集候选建立人工审核清单，保留各自来源与 SHA；不是直接发布。
2. 当前供应商酒店、正式酒店、房型 ID 与历史编号逐项匹配，特别核对上列两组编号差异及共享图片是否适用。
3. 酒店对选定图片权利人、GO 分发范围及依据作明确声明，再走现有原图授权与可信绑定审核。
4. 补牵星图片及其他原图缺口；另行核实当前地址、联系方式、设施、政策，媒体归档本身不足以证明信息完整度 100%。

当前审核绑定、发布和手机端回读均未执行。完整每文件哈希、尺寸、格式和三份压缩包哈希见同目录 AOLUGUYA_ARCHIVE_RECOVERY.json。未将敏感客人信息收入记录。
