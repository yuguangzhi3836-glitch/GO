# bd5665 必需浏览器门禁失败

固定head `bd56659268b1158ac972e07f0ed69b61ca8abd90` 的 browser run36128357084/job108049614135 FAIL。artifact10860154679原ZIP SHA256 `839a1ca8123217c8fe3d85574c5e4d92f9af6ab8c14081138627c4785fa630cf` 与API digest一致；146个内嵌payload hash及source绑定独立验证通过。失败原件保留 `browser-bd5665/`。

必需真实旅程26项中25 PASS、1 FAIL：初始双offer政策激活等待premium的新版本[data-confirm]超时。operations.policy只2条而非3，complete=false；独立SQL按此前置断言HOLD，orders=[]。因此不能把2个租车旅程页面PASS冒称独立SQL资金核对也通过。新争议申诉结算、无损释放、政策换版撤销、只读拒绝四条虽各自PASS，整体门禁仍FAIL。

额外必需mock widget 5项中1 PASS、4 FAIL：正常提交、未知重试、陈旧拒绝均timeout，禁用storage后的错误提示为空。已通知root和C12。静态根因线索为mock origin `http://rental.test/` 非安全上下文，submit先调用crypto.randomUUID；需执行probe证明，不能在本报告直接断定产品无问题。建议保持所有断言，以HTTPS隔离拦截origin匹配支持的安全环境。

政策初始化另一待验证线索：policyPage对同hash URL重复goto，只等待已存在元素，第二次checker可能仍留旧diag DOM。应验证实际刷新和目标版本读回，不以加长timeout掩盖。作者负责修复，C13只读复审。修复后须新固定head及完整门禁，不覆盖本失败记录。
