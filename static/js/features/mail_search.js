        const mailSearchState = {
            initialized: false,
            jobId: '',
            pollTimer: null,
            results: [],
            viewGroups: [],
            selected: new Set(),
            collapsedAccounts: new Set(),
            expandedSubjects: new Set(),
            running: false,
        };

        function selectedMailSearchValues(name) {
            return Array.from(document.querySelectorAll(`input[name="${name}"]:checked`)).map(item => item.value);
        }

        async function initMailSearch() {
            if (!mailSearchState.initialized) {
                const results = document.getElementById('mailSearchResults');
                if (results) results.addEventListener('click', handleMailSearchResultClick);
                mailSearchState.initialized = true;
            }
            if ((!Array.isArray(groups) || groups.length === 0) && typeof loadGroups === 'function') {
                await loadGroups();
            }
            populateMailSearchGroups();
            syncMailSearchScopeUi();
        }

        function populateMailSearchGroups() {
            const select = document.getElementById('mailSearchGroup');
            if (!select) return;
            const current = select.value || 'all';
            const options = ['<option value="all">全部分组</option>'];
            (Array.isArray(groups) ? groups : []).forEach(group => {
                if (typeof isTempMailboxGroup === 'function' && isTempMailboxGroup(group)) return;
                options.push(`<option value="${Number(group.id)}">${escapeHtml(group.name || '')}</option>`);
            });
            select.innerHTML = options.join('');
            if (Array.from(select.options).some(option => option.value === current)) select.value = current;
        }

        function syncMailSearchScopeUi() {
            const scope = document.getElementById('mailSearchMailboxScope')?.value || 'regular';
            const groupSelect = document.getElementById('mailSearchGroup');
            if (!groupSelect) return;
            groupSelect.disabled = false;
            groupSelect.title = scope === 'temp'
                ? '按临时邮箱所属分组筛选'
                : scope === 'all' ? '同时限定普通邮箱和临时邮箱分组' : '限定普通邮箱分组';
        }

        function setMailSearchRunning(running) {
            mailSearchState.running = Boolean(running);
            const submit = document.getElementById('mailSearchSubmit');
            const cancel = document.getElementById('mailSearchCancel');
            if (submit) submit.disabled = running;
            if (cancel) cancel.disabled = !running;
        }

        async function startMailSearch() {
            const query = String(document.getElementById('mailSearchQuery')?.value || '').trim();
            const fields = selectedMailSearchValues('mailSearchField');
            const folders = selectedMailSearchValues('mailSearchFolder');
            if (!query) {
                showToast('请输入检索内容', 'error');
                return;
            }
            if (!fields.length || !folders.length) {
                showToast('至少选择一个匹配范围和邮件文件夹', 'error');
                return;
            }

            if (mailSearchState.pollTimer) clearTimeout(mailSearchState.pollTimer);
            mailSearchState.selected.clear();
            mailSearchState.results = [];
            mailSearchState.viewGroups = [];
            mailSearchState.collapsedAccounts.clear();
            mailSearchState.expandedSubjects.clear();
            updateMailSearchBatchBar();
            renderMailSearchEmpty('正在创建检索任务…');
            updateMailSearchProgress({ total_accounts: 0, scanned_accounts: 0, scanned_messages: 0 }, 'queued');
            setMailSearchRunning(true);

            const groupValue = document.getElementById('mailSearchGroup')?.value || 'all';
            const payload = {
                query,
                regex: Boolean(document.getElementById('mailSearchRegex')?.checked),
                fields,
                folders,
                mailbox_scope: document.getElementById('mailSearchMailboxScope')?.value || 'regular',
                group_id: groupValue,
                account_query: String(document.getElementById('mailSearchAccount')?.value || '').trim(),
                top_per_folder: Number(document.getElementById('mailSearchTop')?.value || 20),
            };

            try {
                const response = await fetch('/api/mail-search', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                const data = await response.json();
                if (!response.ok || !data.success) {
                    handleApiError(data, '创建检索任务失败');
                    setMailSearchRunning(false);
                    return;
                }
                mailSearchState.jobId = data.job.job_id;
                pollMailSearch();
            } catch (error) {
                setMailSearchRunning(false);
                renderMailSearchEmpty('检索请求失败');
                showToast('检索请求失败', 'error');
            }
        }

        function mailSearchResultsChanged(nextResults) {
            if (nextResults.length !== mailSearchState.results.length) return true;
            return nextResults.some((result, index) => (
                mailSearchResultKey(result, index) !== mailSearchResultKey(mailSearchState.results[index], index)
            ));
        }

        async function pollMailSearch() {
            if (!mailSearchState.jobId) return;
            try {
                const response = await fetch(`/api/mail-search/${encodeURIComponent(mailSearchState.jobId)}`);
                const data = await response.json();
                if (!response.ok || !data.success) throw new Error('poll failed');
                const job = data.job || {};
                updateMailSearchProgress(job.progress || {}, job.status, job.summary || {});
                const nextResults = Array.isArray(job.results) ? job.results : [];
                const resultsChanged = mailSearchResultsChanged(nextResults);
                if (resultsChanged) {
                    mailSearchState.results = nextResults;
                    renderMailSearchResults();
                }
                if (job.status === 'completed') {
                    if (!nextResults.length) renderMailSearchEmpty('没有找到匹配邮件');
                    setMailSearchRunning(false);
                    return;
                }
                if (job.status === 'failed' || job.status === 'cancelled') {
                    setMailSearchRunning(false);
                    if (!mailSearchState.results.length) {
                        renderMailSearchEmpty(job.status === 'cancelled' ? '检索已停止' : '检索失败');
                    }
                    return;
                }
                mailSearchState.pollTimer = setTimeout(pollMailSearch, 500);
            } catch (error) {
                mailSearchState.pollTimer = setTimeout(pollMailSearch, 1600);
            }
        }

        async function cancelMailSearch() {
            if (!mailSearchState.jobId || !mailSearchState.running) return;
            try {
                await fetch(`/api/mail-search/${encodeURIComponent(mailSearchState.jobId)}/cancel`, { method: 'POST' });
            } finally {
                setMailSearchRunning(false);
            }
        }

        function updateMailSearchProgress(progress = {}, status = '', summary = {}) {
            const total = Number(progress.total_accounts || 0);
            const scanned = Number(progress.scanned_accounts || 0);
            const messages = Number(progress.scanned_messages || 0);
            const percent = total > 0 ? Math.min(100, Math.round(scanned * 100 / total)) : 0;
            const statusEl = document.getElementById('mailSearchStatus');
            const summaryEl = document.getElementById('mailSearchSummary');
            const progressBar = document.getElementById('mailSearchProgressBar');
            if (statusEl) {
                statusEl.textContent = status === 'completed'
                    ? '检索完成'
                    : status === 'queued' ? '等待执行' : `正在扫描 ${scanned}/${total || '…'} 个邮箱`;
            }
            if (summaryEl) {
                const matches = Number(summary.total_matches || 0);
                summaryEl.textContent = `已检查 ${messages} 封，匹配 ${matches} 封${summary.truncated ? '，结果列表已截断' : ''}`;
            }
            if (progressBar) progressBar.style.width = `${status === 'completed' ? 100 : percent}%`;
        }

        function renderMailSearchEmpty(message) {
            const results = document.getElementById('mailSearchResults');
            if (results) {
                results.innerHTML = `<div class="mail-search-empty">${escapeHtml(message || '暂无检索结果')}</div>`;
            }
            mailSearchState.viewGroups = [];
            const selectAll = document.getElementById('mailSearchSelectAll');
            if (selectAll) {
                selectAll.checked = false;
                selectAll.indeterminate = false;
            }
            updateMailSearchResultSummary();
        }

        function mailSearchResultKey(result, index = -1) {
            const messageId = String(result?.message_id || '').trim() || `index-${index}`;
            const sourceType = String(result?.source_type || 'regular');
            const email = normalizeMailSearchGroupText(result?.email);
            return `${sourceType}:${email}:${Number(result?.account_id) || 0}:${String(result?.folder || '')}:${messageId}`;
        }

        function isTempMailSearchResult(result) {
            return String(result?.source_type || '').toLowerCase() === 'temp'
                || String(result?.method_key || '').toLowerCase() === 'temp';
        }

        function isAccountBackedTempMailSearchResult(result) {
            return isTempMailSearchResult(result) && Boolean(result?.account_backed) && Number(result?.account_id) > 0;
        }

        function mailSearchSourceLabel(result) {
            return isTempMailSearchResult(result) ? '临时邮箱' : '普通邮箱';
        }

        function normalizeMailSearchGroupText(value) {
            return String(value || '').trim().replace(/\s+/g, ' ').toLocaleLowerCase();
        }

        function buildMailSearchViewGroups() {
            const accountMap = new Map();
            mailSearchState.results.forEach((result, index) => {
                const normalizedEmail = normalizeMailSearchGroupText(result.email);
                const sourceType = isTempMailSearchResult(result) ? 'temp' : 'regular';
                const accountKey = `${sourceType}:${normalizedEmail || `account:${Number(result.account_id) || index}`}`;
                let account = accountMap.get(accountKey);
                if (!account) {
                    account = {
                        key: accountKey,
                        email: String(result.email || ''),
                        items: [],
                        subjects: [],
                        subjectMap: new Map(),
                    };
                    accountMap.set(accountKey, account);
                }

                const item = {
                    result,
                    index,
                    key: mailSearchResultKey(result, index),
                };
                account.items.push(item);

                const displaySubject = String(result.subject || '').trim() || '无主题';
                const normalizedSubject = normalizeMailSearchGroupText(displaySubject) || '__empty_subject__';
                let subject = account.subjectMap.get(normalizedSubject);
                if (!subject) {
                    subject = {
                        key: `${accountKey}\u0000${normalizedSubject}`,
                        subject: displaySubject,
                        items: [],
                    };
                    account.subjectMap.set(normalizedSubject, subject);
                    account.subjects.push(subject);
                }
                subject.items.push(item);
            });

            return Array.from(accountMap.values()).map(account => {
                delete account.subjectMap;
                account.subjects.sort((left, right) => (
                    mailSearchItemTimestamp(mailSearchLatestItem(right.items))
                    - mailSearchItemTimestamp(mailSearchLatestItem(left.items))
                ));
                return account;
            }).sort((left, right) => (
                mailSearchItemTimestamp(mailSearchLatestItem(right.items))
                - mailSearchItemTimestamp(mailSearchLatestItem(left.items))
            ));
        }

        function mailSearchItemTimestamp(item) {
            return item ? (Date.parse(item.result.received_at || '') || 0) : 0;
        }

        function mailSearchSelectionState(items) {
            const selectedCount = items.reduce((count, item) => (
                count + (mailSearchState.selected.has(item.key) ? 1 : 0)
            ), 0);
            return {
                selectedCount,
                checked: items.length > 0 && selectedCount === items.length,
                indeterminate: selectedCount > 0 && selectedCount < items.length,
            };
        }

        function mailSearchLatestItem(items) {
            if (!items.length) return null;
            let latest = items[0];
            let latestTime = Date.parse(latest.result.received_at || '') || 0;
            items.slice(1).forEach(item => {
                const itemTime = Date.parse(item.result.received_at || '') || 0;
                if (itemTime > latestTime) {
                    latest = item;
                    latestTime = itemTime;
                }
            });
            return latest;
        }

        function formatMailSearchDate(value) {
            return escapeHtml(typeof formatDate === 'function' ? formatDate(value) : (value || ''));
        }

        function renderMailSearchMatchTags(items) {
            const labels = { subject: '主题', sender: '发件人', preview: '摘要', body: '正文' };
            const fields = new Set();
            items.forEach(item => (item.result.matched_fields || []).forEach(field => fields.add(field)));
            return Array.from(fields).map(field => (
                `<span class="mail-search-match-tag">${escapeHtml(labels[field] || field)}</span>`
            )).join('');
        }

        function mailSearchSenderSummary(items) {
            const senders = Array.from(new Set(items.map(item => String(item.result.from || '').trim()).filter(Boolean)));
            if (!senders.length) return { text: '未知发件人', title: '' };
            const visible = senders.slice(0, 2);
            return {
                text: visible.join('、') + (senders.length > visible.length ? ` 等 ${senders.length} 个` : ''),
                title: senders.join('、'),
            };
        }

        function mailSearchFolderSummary(items) {
            const labels = Array.from(new Set(items.map(item => (
                item.result.folder === 'junkemail' ? '垃圾邮件' : '收件箱'
            ))));
            return labels.join('、');
        }

        function renderMailSearchMessageRows(subject) {
            return subject.items.map(item => {
                const result = item.result;
                const selected = mailSearchState.selected.has(item.key);
                const folder = result.folder === 'junkemail' ? '垃圾邮件' : '收件箱';
                return `
                    <div class="mail-search-message-row ${selected ? 'selected' : ''}" data-index="${item.index}">
                        <input class="mail-search-row-checkbox" type="checkbox" data-action="select-result"
                               data-index="${item.index}" aria-label="选择此邮件" ${selected ? 'checked' : ''}>
                        <div class="mail-search-message-main">
                            <div class="mail-search-message-meta">
                                <span class="mail-search-sender" title="${escapeHtml(result.from || '')}">${escapeHtml(result.from || '未知发件人')}</span>
                                <span>${folder}</span>
                                <span>${formatMailSearchDate(result.received_at)}</span>
                            </div>
                            <span class="mail-search-excerpt" title="${escapeHtml(result.excerpt || result.preview || '')}">${escapeHtml(result.excerpt || result.preview || '无摘要')}</span>
                            <span class="mail-search-match-tags">${renderMailSearchMatchTags([item])}</span>
                        </div>
                        <div class="mail-search-row-actions">
                            <button class="btn-icon" data-action="view" data-index="${item.index}" title="查看邮件" aria-label="查看邮件">👁</button>
                            <button class="btn-icon" data-action="delete" data-index="${item.index}" title="删除邮件" aria-label="删除邮件">🗑️</button>
                        </div>
                    </div>`;
            }).join('');
        }

        function renderMailSearchSubject(accountIndex, subjectIndex, subject) {
            const selection = mailSearchSelectionState(subject.items);
            const expanded = subject.items.length > 1 && mailSearchState.expandedSubjects.has(subject.key);
            const representative = mailSearchLatestItem(subject.items) || subject.items[0];
            const result = representative.result;
            const sender = mailSearchSenderSummary(subject.items);
            const excerpt = result.excerpt || result.preview || '';
            const disclosure = subject.items.length > 1
                ? `<button class="mail-search-disclosure" data-action="toggle-subject"
                           data-account-index="${accountIndex}" data-subject-index="${subjectIndex}"
                           aria-expanded="${expanded ? 'true' : 'false'}"
                           title="${expanded ? '收起同主题邮件' : '展开同主题邮件'}">${expanded ? '▾' : '▸'}</button>`
                : '<span class="mail-search-disclosure-placeholder" aria-hidden="true"></span>';
            const actions = subject.items.length === 1
                ? `
                    <button class="btn-icon" data-action="view" data-index="${representative.index}" title="查看邮件" aria-label="查看邮件">👁</button>
                    <button class="btn-icon" data-action="delete" data-index="${representative.index}" title="删除邮件" aria-label="删除邮件">🗑️</button>`
                : '';

            return `
                <div class="mail-search-subject-group ${selection.checked ? 'selected' : ''} ${selection.indeterminate ? 'partially-selected' : ''}"
                     data-account-index="${accountIndex}" data-subject-index="${subjectIndex}">
                    <div class="mail-search-subject-row">
                        ${disclosure}
                        <input class="mail-search-row-checkbox" type="checkbox" data-action="select-subject"
                               data-account-index="${accountIndex}" data-subject-index="${subjectIndex}"
                               aria-label="选择此主题下的全部邮件" ${selection.checked ? 'checked' : ''}>
                        <div class="mail-search-subject-main">
                            <div class="mail-search-subject-title-line">
                                <span class="mail-search-subject" title="${escapeHtml(subject.subject)}">${escapeHtml(subject.subject)}</span>
                                <span class="mail-search-count-badge">${subject.items.length} 封</span>
                                <span class="mail-search-match-tags">${renderMailSearchMatchTags(subject.items)}</span>
                            </div>
                            <div class="mail-search-subject-meta">
                                <span title="${escapeHtml(sender.title)}">${escapeHtml(sender.text)}</span>
                                <span>${mailSearchFolderSummary(subject.items)}</span>
                                <span>${formatMailSearchDate(result.received_at)}</span>
                            </div>
                            <span class="mail-search-excerpt" title="${escapeHtml(excerpt)}">${escapeHtml(excerpt || '无摘要')}</span>
                        </div>
                        <div class="mail-search-row-actions">${actions}</div>
                    </div>
                    ${expanded ? `<div class="mail-search-message-list">${renderMailSearchMessageRows(subject)}</div>` : ''}
                </div>`;
        }

        function renderMailSearchAccount(account, accountIndex) {
            const collapsed = mailSearchState.collapsedAccounts.has(account.key);
            const selection = mailSearchSelectionState(account.items);
            const representative = mailSearchLatestItem(account.items) || account.items[0];
            const subjectLabel = account.subjects.length === 1 ? '1 个主题' : `${account.subjects.length} 个主题`;
            const messageLabel = account.items.length === 1 ? '1 封邮件' : `${account.items.length} 封邮件`;
            return `
                <section class="mail-search-account-group ${selection.checked ? 'selected' : ''} ${selection.indeterminate ? 'partially-selected' : ''}"
                         data-account-index="${accountIndex}">
                    <div class="mail-search-account-row">
                        <button class="mail-search-disclosure" data-action="toggle-account" data-account-index="${accountIndex}"
                                aria-expanded="${collapsed ? 'false' : 'true'}"
                                title="${collapsed ? '展开邮箱结果' : '收起邮箱结果'}">${collapsed ? '▸' : '▾'}</button>
                        <input class="mail-search-row-checkbox" type="checkbox" data-action="select-account"
                               data-account-index="${accountIndex}" aria-label="选择此邮箱的全部匹配邮件"
                               ${selection.checked ? 'checked' : ''}>
                        <div class="mail-search-account-main">
                            <button class="btn-link mail-search-email" data-action="open-mailbox"
                                    data-index="${representative.index}" title="打开对应邮箱">${escapeHtml(account.email || '未知邮箱')}</button>
                            <div class="mail-search-account-meta">
                                <span>${mailSearchSourceLabel(representative.result)}</span>
                                <span>${subjectLabel}</span>
                                <span>${messageLabel}</span>
                                <span>最新 ${formatMailSearchDate(representative.result.received_at)}</span>
                            </div>
                        </div>
                    </div>
                    ${collapsed ? '' : `
                        <div class="mail-search-account-content">
                            ${account.subjects.map((subject, subjectIndex) => (
                                renderMailSearchSubject(accountIndex, subjectIndex, subject)
                            )).join('')}
                        </div>`}
                </section>`;
        }

        function renderMailSearchResults() {
            const results = document.getElementById('mailSearchResults');
            const wrap = document.getElementById('mailSearchResultsWrap');
            if (!results) return;
            if (!mailSearchState.results.length) {
                renderMailSearchEmpty('没有找到匹配邮件');
                updateMailSearchBatchBar();
                return;
            }

            const previousScrollTop = wrap ? wrap.scrollTop : 0;
            mailSearchState.viewGroups = buildMailSearchViewGroups();
            const accountKeys = new Set(mailSearchState.viewGroups.map(account => account.key));
            const subjectKeys = new Set(mailSearchState.viewGroups.flatMap(account => account.subjects.map(subject => subject.key)));
            mailSearchState.collapsedAccounts = new Set(
                Array.from(mailSearchState.collapsedAccounts).filter(key => accountKeys.has(key))
            );
            mailSearchState.expandedSubjects = new Set(
                Array.from(mailSearchState.expandedSubjects).filter(key => subjectKeys.has(key))
            );

            results.innerHTML = mailSearchState.viewGroups.map(renderMailSearchAccount).join('');
            syncMailSearchSelectionUi();
            updateMailSearchResultSummary();
            if (wrap) wrap.scrollTop = previousScrollTop;
        }

        function updateMailSearchResultSummary() {
            const summary = document.getElementById('mailSearchResultSummary');
            if (!summary) return;
            const accountCount = mailSearchState.viewGroups.length;
            const subjectCount = mailSearchState.viewGroups.reduce((count, account) => count + account.subjects.length, 0);
            const messageCount = mailSearchState.results.length;
            summary.textContent = messageCount
                ? `${accountCount} 个邮箱 · ${subjectCount} 个主题 · ${messageCount} 封邮件`
                : '';
        }

        function setMailSearchCheckboxState(checkbox, state) {
            if (!checkbox) return;
            checkbox.checked = state.checked;
            checkbox.indeterminate = state.indeterminate;
        }

        function syncMailSearchSelectionUi() {
            const allItems = mailSearchState.results.map((result, index) => ({
                result,
                index,
                key: mailSearchResultKey(result, index),
            }));
            setMailSearchCheckboxState(
                document.getElementById('mailSearchSelectAll'),
                mailSearchSelectionState(allItems)
            );

            document.querySelectorAll('#mailSearchResults input[data-action="select-account"]').forEach(checkbox => {
                const account = mailSearchState.viewGroups[Number(checkbox.dataset.accountIndex)];
                if (!account) return;
                const state = mailSearchSelectionState(account.items);
                setMailSearchCheckboxState(checkbox, state);
                const group = checkbox.closest('.mail-search-account-group');
                group?.classList.toggle('selected', state.checked);
                group?.classList.toggle('partially-selected', state.indeterminate);
            });

            document.querySelectorAll('#mailSearchResults input[data-action="select-subject"]').forEach(checkbox => {
                const account = mailSearchState.viewGroups[Number(checkbox.dataset.accountIndex)];
                const subject = account?.subjects[Number(checkbox.dataset.subjectIndex)];
                if (!subject) return;
                const state = mailSearchSelectionState(subject.items);
                setMailSearchCheckboxState(checkbox, state);
                const group = checkbox.closest('.mail-search-subject-group');
                group?.classList.toggle('selected', state.checked);
                group?.classList.toggle('partially-selected', state.indeterminate);
            });

            document.querySelectorAll('#mailSearchResults input[data-action="select-result"]').forEach(checkbox => {
                const index = Number(checkbox.dataset.index);
                const result = mailSearchState.results[index];
                if (!result) return;
                const checked = mailSearchState.selected.has(mailSearchResultKey(result, index));
                checkbox.checked = checked;
                checkbox.indeterminate = false;
                checkbox.closest('.mail-search-message-row')?.classList.toggle('selected', checked);
            });

            updateMailSearchBatchBar();
        }

        function handleMailSearchResultClick(event) {
            const target = event.target.closest('[data-action]');
            if (!target) return;
            const action = target.dataset.action;
            const index = Number(target.dataset.index);
            const accountIndex = Number(target.dataset.accountIndex);
            const subjectIndex = Number(target.dataset.subjectIndex);

            if (action === 'toggle-account') toggleMailSearchAccount(accountIndex);
            if (action === 'toggle-subject') toggleMailSearchSubject(accountIndex, subjectIndex);
            if (action === 'select-account') toggleMailSearchAccountSelection(accountIndex, Boolean(target.checked));
            if (action === 'select-subject') toggleMailSearchSubjectSelection(accountIndex, subjectIndex, Boolean(target.checked));
            if (action === 'select-result') toggleMailSearchResult(index, Boolean(target.checked));
            if (action === 'view') showMailSearchDetail(index);
            if (action === 'delete') deleteMailSearchMessage(index);
            if (action === 'open-mailbox') openMailSearchMailbox(index);
        }

        function toggleMailSearchAccount(accountIndex) {
            const account = mailSearchState.viewGroups[accountIndex];
            if (!account) return;
            if (mailSearchState.collapsedAccounts.has(account.key)) {
                mailSearchState.collapsedAccounts.delete(account.key);
            } else {
                mailSearchState.collapsedAccounts.add(account.key);
            }
            renderMailSearchResults();
        }

        function toggleMailSearchSubject(accountIndex, subjectIndex) {
            const subject = mailSearchState.viewGroups[accountIndex]?.subjects[subjectIndex];
            if (!subject || subject.items.length < 2) return;
            if (mailSearchState.expandedSubjects.has(subject.key)) {
                mailSearchState.expandedSubjects.delete(subject.key);
            } else {
                mailSearchState.expandedSubjects.add(subject.key);
            }
            renderMailSearchResults();
        }

        function setMailSearchItemsSelected(items, selected) {
            items.forEach(item => {
                if (selected) mailSearchState.selected.add(item.key);
                else mailSearchState.selected.delete(item.key);
            });
            syncMailSearchSelectionUi();
        }

        function toggleMailSearchAccountSelection(accountIndex, selected) {
            const account = mailSearchState.viewGroups[accountIndex];
            if (account) setMailSearchItemsSelected(account.items, selected);
        }

        function toggleMailSearchSubjectSelection(accountIndex, subjectIndex, selected) {
            const subject = mailSearchState.viewGroups[accountIndex]?.subjects[subjectIndex];
            if (subject) setMailSearchItemsSelected(subject.items, selected);
        }

        function toggleMailSearchResult(index, selected) {
            const result = mailSearchState.results[index];
            if (!result) return;
            const key = mailSearchResultKey(result, index);
            if (selected) mailSearchState.selected.add(key);
            else mailSearchState.selected.delete(key);
            syncMailSearchSelectionUi();
        }

        function toggleAllMailSearchResults(selected) {
            mailSearchState.selected.clear();
            if (selected) {
                mailSearchState.results.forEach((result, index) => {
                    mailSearchState.selected.add(mailSearchResultKey(result, index));
                });
            }
            syncMailSearchSelectionUi();
        }

        function selectedMailSearchResults() {
            return mailSearchState.results.filter((result, index) => (
                mailSearchState.selected.has(mailSearchResultKey(result, index))
            ));
        }

        function selectedMailSearchAccountIds() {
            return Array.from(new Set(
                selectedMailSearchResults()
                    .filter(item => !isTempMailSearchResult(item) || isAccountBackedTempMailSearchResult(item))
                    .map(item => Number(item.account_id))
                    .filter(Boolean)
            ));
        }

        function selectedMailSearchDeletableAccountIds() {
            return Array.from(new Set(
                selectedMailSearchResults()
                    .filter(item => !isTempMailSearchResult(item))
                    .map(item => Number(item.account_id))
                    .filter(Boolean)
            ));
        }

        function updateMailSearchBatchBar() {
            const bar = document.getElementById('mailSearchBatchBar');
            const count = document.getElementById('mailSearchSelectedCount');
            const messageCount = mailSearchState.selected.size;
            const accountCount = selectedMailSearchAccountIds().length;
            const deletableAccountCount = selectedMailSearchDeletableAccountIds().length;
            if (bar) bar.style.display = messageCount ? 'flex' : 'none';
            if (count) count.textContent = messageCount
                ? `已选 ${messageCount} 封 · ${accountCount} 个关联邮箱`
                : '已选 0 封';
            const moveButton = document.getElementById('mailSearchMoveAccounts');
            const deleteAccountsButton = document.getElementById('mailSearchDeleteAccounts');
            if (moveButton) moveButton.disabled = accountCount === 0;
            if (deleteAccountsButton) deleteAccountsButton.disabled = deletableAccountCount === 0;
        }

        async function showMailSearchDetail(index) {
            const result = mailSearchState.results[index];
            if (!result) return;
            const modal = document.getElementById('mailSearchDetailModal');
            const title = document.getElementById('mailSearchDetailTitle');
            const body = document.getElementById('mailSearchDetailBody');
            if (title) title.textContent = result.subject || '邮件详情';
            if (body) body.innerHTML = '<div class="loading-overlay"><span class="spinner"></span> 获取中…</div>';
            if (modal) modal.classList.add('show');
            try {
                let url;
                if (isTempMailSearchResult(result)) {
                    url = `/api/temp-emails/${encodeURIComponent(result.email)}/messages/${encodeURIComponent(result.message_id)}?refresh_if_missing=0`;
                } else {
                    const detailMethod = String(result.method_key || '').startsWith('imap_') ? 'imap' : 'graph';
                    url = `/api/email/${encodeURIComponent(result.email)}/${encodeURIComponent(result.message_id)}?folder=${encodeURIComponent(result.folder)}&method=${detailMethod}`;
                }
                const response = await fetch(url);
                const data = await response.json();
                if (!response.ok || !data.success) throw new Error('detail failed');
                const detail = data.email || data.data || {};
                const rawBody = typeof detail.body === 'object' ? detail.body.content : (detail.body || detail.content || detail.body_text || '');
                body.innerHTML = `
                    <dl class="mail-search-detail-meta">
                        <dt>邮箱</dt><dd>${escapeHtml(result.email || '')}</dd>
                        <dt>发件人</dt><dd>${escapeHtml(detail.from || detail.from_address || result.from || '')}</dd>
                        <dt>主题</dt><dd>${escapeHtml(detail.subject || result.subject || '')}</dd>
                        <dt>时间</dt><dd>${escapeHtml(detail.date || detail.receivedDateTime || result.received_at || '')}</dd>
                    </dl>
                    <div class="mail-search-detail-content">${escapeHtml(rawBody || '无正文内容')}</div>`;
            } catch (error) {
                if (body) body.innerHTML = '<div class="empty-state"><span class="empty-icon">⚠️</span><p>获取邮件详情失败</p></div>';
            }
        }

        function closeMailSearchDetail() {
            document.getElementById('mailSearchDetailModal')?.classList.remove('show');
        }

        async function openMailSearchMailbox(index) {
            const result = mailSearchState.results[index];
            if (!result) return;
            if (isTempMailSearchResult(result) && !isAccountBackedTempMailSearchResult(result)) {
                navigate('temp-emails');
                if (typeof selectTempEmail === 'function') selectTempEmail(result.email);
                return;
            }
            navigate('mailbox');
            if (result.group_id && typeof selectGroup === 'function') await selectGroup(Number(result.group_id));
            if (typeof selectAccount === 'function') selectAccount(result.email);
        }

        async function deleteMailSearchGroup(items) {
            const tempItems = items.filter(isTempMailSearchResult);
            const regularItems = items.filter(item => !isTempMailSearchResult(item));
            let successCount = 0;
            let uncertainCount = 0;
            const deletedKeys = new Set();

            for (const item of tempItems) {
                const response = await fetch(
                    `/api/temp-emails/${encodeURIComponent(item.email)}/messages/${encodeURIComponent(item.message_id)}`,
                    { method: 'DELETE' }
                );
                const data = await response.json();
                if (response.ok && data.success) {
                    successCount += 1;
                    deletedKeys.add(mailSearchResultKey(item));
                }
            }

            const grouped = new Map();
            regularItems.forEach(item => {
                const key = `${item.email}\n${item.folder}`;
                if (!grouped.has(key)) grouped.set(key, { email: item.email, folder: item.folder, items: [] });
                grouped.get(key).items.push(item);
            });
            for (const group of grouped.values()) {
                const ids = group.items.map(item => item.message_id);
                const response = await fetch('/api/emails/delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email: group.email, folder: group.folder, ids }),
                });
                const data = await response.json();
                const groupSuccessCount = Math.max(0, Math.min(ids.length, Number(data.success_count || (data.success ? ids.length : 0))));
                successCount += groupSuccessCount;
                if (groupSuccessCount === ids.length) {
                    group.items.forEach(item => deletedKeys.add(mailSearchResultKey(item)));
                } else if (groupSuccessCount > 0) {
                    uncertainCount += groupSuccessCount;
                }
            }
            if (tempItems.length && typeof accountsCache !== 'undefined') delete accountsCache['temp'];
            return { successCount, uncertainCount, deletedKeys };
        }

        async function deleteMailSearchMessage(index) {
            const result = mailSearchState.results[index];
            if (!result || !window.confirm(`确定删除“${result.subject || '无主题'}”吗？`)) return;
            const key = mailSearchResultKey(result, index);
            const outcome = await deleteMailSearchGroup([result]);
            if (outcome.successCount > 0) {
                if (outcome.deletedKeys.has(key)) mailSearchState.results.splice(index, 1);
                mailSearchState.selected.delete(key);
                renderMailSearchResults();
                showToast(outcome.uncertainCount ? '邮件已删除，请重新检索确认结果' : '邮件已删除', 'success');
            } else {
                showToast('邮件删除失败', 'error');
            }
        }

        async function deleteSelectedMailSearchMessages() {
            const items = selectedMailSearchResults();
            if (!items.length || !window.confirm(`确定删除选中的 ${items.length} 封邮件吗？`)) return;
            const outcome = await deleteMailSearchGroup(items);
            if (outcome.successCount > 0) {
                mailSearchState.results = mailSearchState.results.filter(item => !outcome.deletedKeys.has(mailSearchResultKey(item)));
                mailSearchState.selected.clear();
                renderMailSearchResults();
                const suffix = outcome.uncertainCount ? '，部分普通邮件需重新检索确认' : '';
                showToast(`已删除 ${outcome.successCount} 封邮件${suffix}`, outcome.uncertainCount ? 'warning' : 'success');
            } else {
                showToast('没有邮件被删除', 'error');
            }
        }

        async function moveSelectedMailSearchAccounts() {
            const accountIds = selectedMailSearchAccountIds();
            if (!accountIds.length) {
                showToast('请选择关联的普通邮箱', 'error');
                return;
            }
            if (typeof showBatchMoveGroupModal !== 'function') {
                showToast('移动分组功能暂不可用', 'error');
                return;
            }
            await showBatchMoveGroupModal({
                scopedAccountIds: accountIds,
                onSuccess: ({ groupId, accountIds: movedAccountIds }) => {
                    const moved = new Set(movedAccountIds.map(Number));
                    mailSearchState.results.forEach(result => {
                        if (moved.has(Number(result.account_id))) result.group_id = Number(groupId);
                    });
                    mailSearchState.selected.clear();
                    if (typeof accountsCache !== 'undefined') {
                        Object.keys(accountsCache).forEach(key => delete accountsCache[key]);
                    }
                    syncMailSearchSelectionUi();
                },
            });
        }

        async function deleteSelectedMailSearchAccounts() {
            const accountIds = selectedMailSearchDeletableAccountIds();
            if (!accountIds.length || !window.confirm(`确定删除关联的 ${accountIds.length} 个邮箱账号吗？此操作不会撤销。`)) return;
            const response = await fetch('/api/accounts/batch-delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ account_ids: accountIds }),
            });
            const data = await response.json();
            if (!response.ok || !data.success) {
                handleApiError(data, '删除关联账号失败');
                return;
            }
            const deleted = new Set(accountIds);
            mailSearchState.results = mailSearchState.results.filter(item => !deleted.has(Number(item.account_id)));
            mailSearchState.selected.clear();
            renderMailSearchResults();
            showToast(data.message || '关联账号已删除', 'success');
            if (typeof accountsCache !== 'undefined') Object.keys(accountsCache).forEach(key => delete accountsCache[key]);
        }
