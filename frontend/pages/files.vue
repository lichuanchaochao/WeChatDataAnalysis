<template>
  <div class="records-page records-page--files">
    <div class="records-page__scroll">
      <main class="records-page__frame">
        <!-- Masthead -->
        <header class="records-masthead">
          <div class="records-masthead__identity">
            <div class="records-masthead__title-group">
              <h1>文件管理</h1>
              <span class="records-masthead__count">
                共<strong>{{ summary.total_count || total }}</strong>个文件
                <span v-if="summary.local_ready_count" class="text-xs text-emerald-600 font-medium ml-1.5">
                  (本地就绪 {{ summary.local_ready_count }} 个)
                </span>
              </span>
            </div>
          </div>

          <div class="records-masthead__actions">
            <!-- Search Box -->
            <label class="records-search">
              <i class="fa-solid fa-magnifying-glass" aria-hidden="true"></i>
              <input v-model="keyword" type="search" aria-label="搜索文件" placeholder="搜索文件名、来源群聊、发送人" autocomplete="off" />
              <button v-if="keyword" type="button" class="records-search__clear" title="清空搜索" aria-label="清空搜索" @click="keyword = ''">
                <i class="fa-solid fa-xmark" aria-hidden="true"></i>
              </button>
            </label>

            <!-- Categorized Export to Local -->
            <button
              type="button"
              class="records-action-button text-xs px-3 py-1.5 rounded-lg bg-[#07c160] hover:bg-[#06ae56] text-white flex items-center gap-1.5 font-medium transition shadow-sm"
              title="按来源与格式分类归档到本地"
              @click="openExportModal"
            >
              <i class="fa-solid fa-folder-tree" aria-hidden="true"></i>
              <span>分类归档到本地</span>
            </button>

            <!-- Refresh Button -->
            <button
              type="button"
              class="records-icon-button"
              :title="loading ? '正在刷新' : '刷新文件列表'"
              :aria-label="loading ? '正在刷新' : '刷新文件列表'"
              :disabled="loading"
              @click="loadItems()"
            >
              <i class="fa-solid fa-arrow-rotate-right" :class="{ 'fa-spin': loading }" aria-hidden="true"></i>
            </button>
          </div>
        </header>

        <!-- Main Body -->
        <section class="records-body files-container" aria-label="文件列表">
          <!-- Filters Toolbar -->
          <div class="files-toolbar flex flex-col gap-3 pb-3 border-b border-gray-100">
            <!-- Row 1: Source Selector & Specific Source Dropdown & Hidden Manager -->
            <div class="flex items-center justify-between gap-3 flex-wrap">
              <!-- Left: Source Big Categories -->
              <div class="flex items-center gap-2">
                <span class="text-xs text-gray-400 font-medium mr-1">来源出处:</span>
                <button
                  v-for="s in sourceOptions"
                  :key="s.value"
                  type="button"
                  class="px-2.5 py-1 text-xs rounded-md transition font-medium"
                  :class="sourceFilter === s.value ? 'bg-gray-800 text-white shadow-sm' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'"
                  @click="sourceFilter = s.value"
                >
                  {{ s.label }}
                  <span class="ml-1 opacity-75">({{ s.count }})</span>
                </button>
              </div>

              <!-- Right: Specific Source Selector & Hidden Sources Manager Badge -->
              <div class="flex items-center gap-2">
                <!-- Specific Source Selector Dropdown -->
                <div class="relative" ref="sourceDropdownRef">
                  <div class="flex items-center gap-1">
                    <button
                      type="button"
                      class="px-3 py-1 text-xs rounded-md border transition font-medium flex items-center gap-1.5 shadow-xs"
                      :class="specificSourceId ? 'bg-blue-50 text-blue-700 border-blue-300' : 'bg-white text-gray-700 border-gray-200 hover:bg-gray-50'"
                      @click="sourceDropdownOpen = !sourceDropdownOpen"
                    >
                      <i class="fa-solid" :class="specificSourceId ? 'fa-user-check text-blue-600' : 'fa-users text-gray-500'"></i>
                      <span class="max-w-[170px] truncate">{{ currentSpecificSourceTitle }}</span>
                      <i class="fa-solid fa-chevron-down text-[10px] opacity-60"></i>
                    </button>

                    <button
                      v-if="specificSourceId"
                      type="button"
                      class="w-5 h-5 rounded flex items-center justify-center text-gray-400 hover:text-gray-600 hover:bg-gray-200 transition text-xs"
                      title="清除按群筛选"
                      @click="clearSpecificSource"
                    >
                      <i class="fa-solid fa-xmark"></i>
                    </button>
                  </div>

                  <!-- Dropdown Menu -->
                  <div
                    v-if="sourceDropdownOpen"
                    class="absolute right-0 top-full mt-1.5 z-40 bg-white border border-gray-200 shadow-xl rounded-xl w-72 p-2 flex flex-col gap-1.5 animate-in fade-in zoom-in-95 duration-100"
                  >
                    <!-- Search input inside dropdown -->
                    <div class="relative px-1 pt-1">
                      <i class="fa-solid fa-magnifying-glass absolute left-3 top-3 text-xs text-gray-400"></i>
                      <input
                        v-model="sourceSearchQuery"
                        type="text"
                        placeholder="过滤群聊或联系人..."
                        class="w-full pl-7 pr-2.5 py-1 text-xs bg-gray-50 border border-gray-200 rounded-lg focus:outline-hidden focus:border-[#07c160]"
                      />
                    </div>

                    <div class="max-h-60 overflow-y-auto flex flex-col gap-0.5 pt-1">
                      <button
                        type="button"
                        class="text-left px-2.5 py-1.5 text-xs rounded-lg hover:bg-gray-100 flex items-center justify-between transition"
                        :class="{ 'font-semibold text-[#07c160] bg-[#07c160]/10': !specificSourceId }"
                        @click="selectSpecificSource('')"
                      >
                        <span>全部群聊与好友</span>
                        <span class="text-[11px] opacity-60">{{ summary.total_count || total }}</span>
                      </button>

                      <button
                        v-for="src in filteredAvailableSources"
                        :key="src.source_id"
                        type="button"
                        class="text-left px-2.5 py-1.5 text-xs rounded-lg hover:bg-gray-100 flex items-center justify-between transition"
                        :class="{ 'font-semibold text-blue-600 bg-blue-50': specificSourceId === src.source_id }"
                        @click="selectSpecificSource(src.source_id, src.source_title)"
                      >
                        <span class="truncate max-w-[190px] flex items-center gap-1.5">
                          <i class="fa-solid text-[11px]" :class="src.is_group ? 'fa-users text-blue-500' : 'fa-user text-gray-500'"></i>
                          <span class="truncate" :title="src.source_title">{{ src.source_title }}</span>
                        </span>
                        <span class="text-[11px] font-mono opacity-60 ml-2">({{ src.count }})</span>
                      </button>

                      <div v-if="!filteredAvailableSources.length" class="text-center py-4 text-xs text-gray-400">
                        未找到匹配的来源
                      </div>
                    </div>
                  </div>
                </div>

                <!-- Hidden Sources Manager Button -->
                <button
                  v-if="hiddenSourceIds.length > 0"
                  type="button"
                  class="px-2.5 py-1 text-xs rounded-md bg-amber-50 hover:bg-amber-100 text-amber-800 border border-amber-200 transition font-medium flex items-center gap-1.5 shadow-xs"
                  title="管理已隐藏的群聊和来源"
                  @click="hiddenManagerModalOpen = true"
                >
                  <i class="fa-solid fa-eye-slash text-xs"></i>
                  <span>已隐藏 {{ hiddenSourceIds.length }} 个来源 (点击恢复)</span>
                </button>
              </div>
            </div>

            <!-- Row 2: Category Selector -->
            <div class="flex items-center gap-1.5 flex-wrap">
              <span class="text-xs text-gray-400 font-medium mr-1">文件类别:</span>
              <button
                v-for="cat in categoryOptions"
                :key="cat.value"
                type="button"
                class="px-2.5 py-1 text-xs rounded-md transition flex items-center gap-1.5 font-medium"
                :class="categoryFilter === cat.value ? 'bg-[#07c160]/10 text-[#07c160] ring-1 ring-[#07c160]/30 font-semibold' : 'bg-gray-50 text-gray-600 hover:bg-gray-100 border border-gray-200/60'"
                @click="categoryFilter = cat.value"
              >
                <i :class="['fa-solid', cat.icon]" aria-hidden="true"></i>
                <span>{{ cat.label }}</span>
                <span class="text-[11px] opacity-70">({{ cat.count }})</span>
              </button>
            </div>
          </div>

          <!-- Loading / Empty / Error States -->
          <div v-if="loading && !items.length" class="records-state records-state--loading" role="status">
            <div class="records-state__inner">
              <span class="records-state__icon"><i class="fa-solid fa-arrow-rotate-right fa-spin"></i></span>
              <div class="records-state__title">正在读取文件</div>
              <div class="records-state__text">正在扫描微信聊天与收藏数据库</div>
            </div>
          </div>

          <div v-else-if="error" class="records-state records-state--error">
            <div class="records-state__inner">
              <span class="records-state__icon"><i class="fa-solid fa-triangle-exclamation"></i></span>
              <div class="records-state__title">读取失败</div>
              <div class="records-state__text text-red-500">{{ error }}</div>
            </div>
          </div>

          <div v-else-if="!items.length" class="records-state">
            <div class="records-state__inner">
              <span class="records-state__icon"><i class="fa-regular fa-folder-open"></i></span>
              <div class="records-state__title">暂无文件记录</div>
              <div class="records-state__text">当前筛选条件下未找到相关文件</div>
            </div>
          </div>

          <!-- File Items List -->
          <div v-else class="files-list flex flex-col gap-2 pt-2">
            <article
              v-for="file in items"
              :key="file.id"
              class="file-card group bg-white hover:bg-gray-50/80 rounded-xl p-3 border border-gray-100 hover:border-gray-200 transition shadow-[0_1px_3px_rgba(0,0,0,0.02)] flex items-center justify-between gap-4"
            >
              <!-- Left: File Icon + Info -->
              <div class="flex items-center gap-3.5 min-w-0 flex-1">
                <!-- Icon -->
                <div class="w-10 h-10 rounded-lg flex-shrink-0 flex items-center justify-center text-lg" :class="getFileIconClass(file)">
                  <i :class="['fa-solid', getFileIcon(file)]" aria-hidden="true"></i>
                </div>

                <!-- Text Details -->
                <div class="min-w-0 flex-1 flex flex-col gap-1">
                  <!-- Title -->
                  <div class="flex items-center gap-2">
                    <span class="font-medium text-sm text-gray-900 truncate" :title="file.filename">
                      {{ file.filename }}
                    </span>
                    <!-- Source Origin Badge -->
                    <span
                      class="px-1.5 py-0.5 text-[11px] rounded font-medium flex-shrink-0"
                      :class="file.source_type === 'chat' ? 'bg-blue-50 text-blue-700 border border-blue-200/50' : 'bg-amber-50 text-amber-700 border border-amber-200/50'"
                    >
                      {{ file.source_type === 'chat' ? (file.is_group ? '群聊文件' : '私聊文件') : '微信收藏' }}
                    </span>
                  </div>

                  <!-- Metadata Line: Origin Source, Sender, Time, Size -->
                  <div class="flex items-center gap-3 text-xs text-gray-500 flex-wrap">
                    <!-- Source Origin -->
                    <span class="flex items-center gap-1 text-gray-600 font-medium truncate max-w-[200px]" :title="file.source_title">
                      <i class="fa-solid" :class="file.source_type === 'chat' ? (file.is_group ? 'fa-users' : 'fa-user') : 'fa-bookmark'" aria-hidden="true"></i>
                      <span class="truncate">{{ file.source_title }}</span>
                    </span>

                    <span v-if="file.sender_name && file.is_group" class="text-gray-400">
                      发送人: <span class="text-gray-600">{{ file.sender_name }}</span>
                    </span>

                    <span class="text-gray-400">
                      {{ file.time_formatted || '未知时间' }}
                    </span>

                    <span class="text-gray-400 font-mono">
                      {{ file.size_formatted }}
                    </span>

                    <!-- Local Presence Tag -->
                    <span
                      class="inline-flex items-center gap-1 text-[11px] font-medium px-1.5 py-0.2 rounded"
                      :class="file.is_local_exists ? 'text-emerald-700 bg-emerald-50' : 'text-gray-400 bg-gray-50'"
                    >
                      <i class="fa-solid" :class="file.is_local_exists ? 'fa-circle-check' : 'fa-cloud'" aria-hidden="true"></i>
                      {{ file.is_local_exists ? '本地已就绪' : '未下载' }}
                    </span>
                  </div>
                </div>
              </div>

              <!-- Right: Actions -->
              <div class="flex items-center gap-1.5 flex-shrink-0">
                <!-- Focus on this source -->
                <button
                  v-if="file.source_id && specificSourceId !== file.source_id"
                  type="button"
                  class="px-2 py-1 text-xs rounded-md bg-blue-50/70 hover:bg-blue-100 text-blue-700 border border-blue-200/60 flex items-center gap-1 transition"
                  :title="file.is_group ? '仅看该群文件' : '仅看此人文件'"
                  @click="selectSpecificSource(file.source_id, file.source_title)"
                >
                  <i class="fa-solid fa-bullseye text-[11px]"></i>
                  <span>{{ file.is_group ? '仅看该群' : '仅看此人' }}</span>
                </button>

                <!-- Hide this source -->
                <button
                  v-if="file.source_id"
                  type="button"
                  class="px-2 py-1 text-xs rounded-md bg-gray-50 hover:bg-rose-50 text-gray-500 hover:text-rose-600 border border-gray-200/60 hover:border-rose-200 flex items-center gap-1 transition"
                  :title="file.is_group ? '隐藏该群所有文件' : '隐藏此人所有文件'"
                  @click="hideSource(file)"
                >
                  <i class="fa-solid fa-eye-slash text-[11px]"></i>
                  <span>{{ file.is_group ? '隐藏该群' : '隐藏此人' }}</span>
                </button>

                <!-- Open in Finder / Explorer -->
                <button
                  v-if="file.is_local_exists"
                  type="button"
                  class="px-2.5 py-1 text-xs rounded-md bg-gray-100 hover:bg-gray-200 text-gray-700 flex items-center gap-1 transition ml-1"
                  title="在系统访达或资源管理器中定位文件"
                  @click="openFolder(file)"
                >
                  <i class="fa-solid fa-folder-open" aria-hidden="true"></i>
                  <span>访达定位</span>
                </button>

                <!-- Download -->
                <button
                  v-if="file.is_local_exists"
                  type="button"
                  class="px-2.5 py-1 text-xs rounded-md bg-emerald-50 hover:bg-emerald-100 text-emerald-700 border border-emerald-200/60 flex items-center gap-1 transition font-medium"
                  title="直接下载此文件"
                  @click="downloadFile(file)"
                >
                  <i class="fa-solid fa-download" aria-hidden="true"></i>
                  <span>下载</span>
                </button>

                <span v-else class="text-xs text-gray-400 px-2 py-1">
                  需在微信打开后缓存
                </span>
              </div>
            </article>

            <!-- Load More & Load All Area -->
            <div v-if="hasMore" class="flex items-center justify-center gap-3 pt-4 pb-6">
              <button
                type="button"
                class="px-4 py-2 text-xs rounded-lg bg-gray-100 hover:bg-gray-200 text-gray-700 font-medium transition flex items-center gap-2"
                :disabled="loading || loadingAll"
                @click="loadItems({ append: true })"
              >
                <i v-if="loading && !loadingAll" class="fa-solid fa-arrow-rotate-right fa-spin"></i>
                <span>加载更多 (50条)</span>
              </button>

              <button
                type="button"
                class="px-4 py-2 text-xs rounded-lg font-medium transition flex items-center gap-2 bg-[#07c160]/10 hover:bg-[#07c160]/20 text-[#07c160] border border-[#07c160]/30 shadow-xs"
                :disabled="loading || loadingAll"
                @click="loadAllFiles"
              >
                <i v-if="loadingAll" class="fa-solid fa-arrow-rotate-right fa-spin text-sm"></i>
                <i v-else class="fa-solid fa-bolt text-xs"></i>
                <span>{{ loadingAll ? `正在载入中... ${items.length} / ${total}` : `加载全部 (剩余 ${total - items.length} 个)` }}</span>
              </button>
            </div>

            <!-- All Loaded State Indicator -->
            <div v-else-if="items.length > 0 && total > 0" class="flex justify-center items-center gap-2 py-5 text-xs text-gray-400 font-medium">
              <i class="fa-solid fa-circle-check text-emerald-500"></i>
              <span>✓ 已加载全部文件 (共 {{ items.length }} 条)</span>
            </div>
          </div>
        </section>

        <!-- Hidden Sources Management Modal -->
        <div v-if="hiddenManagerModalOpen" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-xs">
          <div class="bg-white rounded-2xl max-w-md w-full p-6 shadow-2xl flex flex-col gap-4 border border-gray-100 animate-in fade-in zoom-in-95 duration-150">
            <div class="flex items-center justify-between pb-3 border-b border-gray-100">
              <div class="flex items-center gap-2">
                <div class="w-8 h-8 rounded-lg bg-amber-50 text-amber-600 flex items-center justify-center">
                  <i class="fa-solid fa-eye-slash"></i>
                </div>
                <h3 class="font-bold text-gray-900 text-base">已隐藏的来源列表</h3>
              </div>
              <button type="button" class="text-gray-400 hover:text-gray-600 p-1" @click="hiddenManagerModalOpen = false">
                <i class="fa-solid fa-xmark text-lg"></i>
              </button>
            </div>

            <div class="text-xs text-gray-500">
              以下来源的文件已在列表中被屏蔽，您可以随时点击右侧按钮恢复显示：
            </div>

            <div class="max-h-64 overflow-y-auto flex flex-col gap-1.5 py-1">
              <div
                v-for="sourceId in hiddenSourceIds"
                :key="sourceId"
                class="p-2.5 rounded-xl bg-gray-50 hover:bg-gray-100/80 border border-gray-100 flex items-center justify-between gap-3 transition"
              >
                <div class="flex items-center gap-2 min-w-0">
                  <i class="fa-solid text-xs text-gray-400" :class="sourceId.endsWith('@chatroom') ? 'fa-users' : 'fa-user'"></i>
                  <span class="text-xs font-medium text-gray-800 truncate" :title="hiddenSourcesMap[sourceId] || sourceId">
                    {{ hiddenSourcesMap[sourceId] || sourceId }}
                  </span>
                </div>
                <button
                  type="button"
                  class="px-2.5 py-1 text-xs rounded-lg bg-white hover:bg-emerald-50 text-emerald-600 border border-gray-200 hover:border-emerald-200 transition font-medium flex-shrink-0"
                  @click="unhideSource(sourceId)"
                >
                  恢复显示
                </button>
              </div>

              <div v-if="!hiddenSourceIds.length" class="text-center py-6 text-xs text-gray-400">
                当前没有隐藏任何来源
              </div>
            </div>

            <div class="flex items-center justify-between pt-3 border-t border-gray-100">
              <button
                v-if="hiddenSourceIds.length > 0"
                type="button"
                class="text-xs text-rose-600 hover:text-rose-700 font-medium"
                @click="unhideAllSources"
              >
                全部恢复显示
              </button>
              <div v-else></div>

              <button
                type="button"
                class="px-4 py-2 text-xs rounded-xl bg-gray-100 hover:bg-gray-200 text-gray-700 font-medium transition"
                @click="hiddenManagerModalOpen = false"
              >
                关闭
              </button>
            </div>
          </div>
        </div>

        <!-- Toast Notification for Hiding Source -->
        <div
          v-if="toastMessage"
          class="fixed bottom-6 right-6 z-50 bg-gray-900/90 text-white text-xs px-4 py-3 rounded-xl shadow-2xl flex items-center gap-3 backdrop-blur-xs animate-in fade-in slide-in-from-bottom-2 duration-150"
        >
          <span>{{ toastMessage }}</span>
          <button
            v-if="toastUndoId"
            type="button"
            class="text-emerald-400 hover:text-emerald-300 font-semibold underline underline-offset-2 transition"
            @click="undoHideSource"
          >
            撤销
          </button>
        </div>

        <!-- Export Categorized Dialog -->
        <div v-if="exportModalOpen" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-xs">
          <div class="bg-white rounded-2xl max-w-lg w-full p-6 shadow-2xl flex flex-col gap-4 border border-gray-100 animate-in fade-in zoom-in-95 duration-150">
            <div class="flex items-center justify-between pb-3 border-b border-gray-100">
              <div class="flex items-center gap-2">
                <div class="w-8 h-8 rounded-lg bg-emerald-50 text-emerald-600 flex items-center justify-center">
                  <i class="fa-solid fa-folder-tree"></i>
                </div>
                <h3 class="font-bold text-gray-900 text-base">分类归档到本地</h3>
              </div>
              <button type="button" class="text-gray-400 hover:text-gray-600 p-1" @click="exportModalOpen = false">
                <i class="fa-solid fa-xmark text-lg"></i>
              </button>
            </div>

            <!-- Overview -->
            <div class="text-xs text-gray-600 leading-relaxed bg-gray-50 p-3.5 rounded-xl border border-gray-100 flex flex-col gap-2">
              <div class="font-semibold text-gray-800 flex items-center gap-1.5">
                <i class="fa-solid fa-circle-info text-blue-500"></i>
                <span>归档说明：系统将为您把所有聊天与收藏文件按来源出处自动整理归类：</span>
              </div>
              <div class="font-mono text-[11px] text-gray-600 bg-white p-2.5 rounded-lg border border-gray-200/60 leading-5">
                📁 微信文件分类归档_[账号]_[时间]/<br />
                ├── 📁 01_聊天文件/<br />
                │   ├── 📁 [群聊] 某群聊/ [文档] 方案.pdf<br />
                │   └── 📁 [私聊] 某好友/ [文档] 合同.docx<br />
                ├── 📁 02_微信收藏/<br />
                │   ├── 📁 doc/ 完课礼.pdf<br />
                │   └── 📁 video/ 录像.mp4<br />
                └── 📄 归档文件清单.csv (记录出处、发送人、大小、时间)
              </div>
              <div class="text-emerald-700 font-medium">
                当前筛选范围内共有 <strong>{{ summary.local_ready_count }}</strong> 个本地已就绪文件可供导出归档。
              </div>
            </div>

            <!-- Export Mode -->
            <div class="flex flex-col gap-1.5">
              <label class="text-xs font-semibold text-gray-700">导出格式：</label>
              <div class="grid grid-cols-2 gap-3">
                <label
                  class="flex items-center gap-2 p-3 rounded-xl border cursor-pointer transition"
                  :class="exportMode === 'folder' ? 'border-[#07c160] bg-[#07c160]/5 text-[#07c160] font-semibold' : 'border-gray-200 hover:bg-gray-50 text-gray-700'"
                >
                  <input v-model="exportMode" type="radio" value="folder" class="hidden" />
                  <i class="fa-solid fa-folder text-base"></i>
                  <span class="text-xs">直接生成结构化文件夹（推荐）</span>
                </label>
                <label
                  class="flex items-center gap-2 p-3 rounded-xl border cursor-pointer transition"
                  :class="exportMode === 'zip' ? 'border-[#07c160] bg-[#07c160]/5 text-[#07c160] font-semibold' : 'border-gray-200 hover:bg-gray-50 text-gray-700'"
                >
                  <input v-model="exportMode" type="radio" value="zip" class="hidden" />
                  <i class="fa-solid fa-file-zipper text-base"></i>
                  <span class="text-xs">打包为 ZIP 压缩包</span>
                </label>
              </div>
            </div>

            <!-- Export Status Feedback -->
            <div v-if="exportStatusMessage" class="text-xs p-3 rounded-xl font-medium" :class="exportStatusType === 'success' ? 'bg-emerald-50 text-emerald-800 border border-emerald-200' : 'bg-red-50 text-red-800 border border-red-200'">
              {{ exportStatusMessage }}
            </div>

            <!-- Action Buttons -->
            <div class="flex items-center justify-end gap-3 pt-2">
              <button
                type="button"
                class="px-4 py-2 text-xs rounded-xl bg-gray-100 hover:bg-gray-200 text-gray-700 font-medium transition"
                :disabled="exportLoading"
                @click="exportModalOpen = false"
              >
                取消
              </button>
              <button
                type="button"
                class="px-5 py-2 text-xs rounded-xl bg-[#07c160] hover:bg-[#06ae56] text-white font-medium transition shadow-md flex items-center gap-1.5"
                :disabled="exportLoading || summary.local_ready_count === 0"
                @click="startExport"
              >
                <i v-if="exportLoading" class="fa-solid fa-arrow-rotate-right fa-spin"></i>
                <i v-else class="fa-solid fa-download"></i>
                <span>{{ exportLoading ? '正在分类整理并导出...' : '开始分类归档' }}</span>
              </button>
            </div>
          </div>
        </div>
      </main>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { useChatAccountsStore } from '~/stores/chatAccounts'

const api = useApi()
const chatAccounts = useChatAccountsStore()

const selectedAccount = computed(() => chatAccounts.selectedAccount || '')

const items = ref([])
const total = ref(0)
const loading = ref(false)
const loadingAll = ref(false)
const error = ref('')
const hasMore = ref(false)

const keyword = ref('')
const sourceFilter = ref('all')
const categoryFilter = ref('all')

// Specific Source Filter
const specificSourceId = ref('')
const specificSourceTitle = ref('')
const availableSources = ref([])
const sourceDropdownOpen = ref(false)
const sourceSearchQuery = ref('')
const sourceDropdownRef = ref(null)

// Hidden Sources Management
const hiddenSourceIds = ref([])
const hiddenSourcesMap = ref({})
const hiddenManagerModalOpen = ref(false)

// Toast
const toastMessage = ref('')
const toastUndoId = ref('')
let toastTimer = null

const summary = ref({
  total_count: 0,
  chat_count: 0,
  favorite_count: 0,
  doc_count: 0,
  video_count: 0,
  voice_count: 0,
  image_count: 0,
  archive_count: 0,
  other_count: 0,
  local_ready_count: 0,
})

let searchTimer = null

const sourceOptions = computed(() => [
  { label: '全部来源', value: 'all', count: summary.value.total_count || 0 },
  { label: '聊天文件', value: 'chat', count: summary.value.chat_count || 0 },
  { label: '微信收藏', value: 'favorite', count: summary.value.favorite_count || 0 },
])

const categoryOptions = computed(() => [
  { label: '全部', value: 'all', icon: 'fa-layer-group', count: summary.value.total_count || 0 },
  { label: '文档', value: 'doc', icon: 'fa-file-lines', count: summary.value.doc_count || 0 },
  { label: '视频', value: 'video', icon: 'fa-film', count: summary.value.video_count || 0 },
  { label: '语音/音频', value: 'voice', icon: 'fa-microphone', count: summary.value.voice_count || 0 },
  { label: '图片', value: 'image', icon: 'fa-image', count: summary.value.image_count || 0 },
  { label: '压缩包', value: 'archive', icon: 'fa-file-zipper', count: summary.value.archive_count || 0 },
  { label: '其它', value: 'other', icon: 'fa-folder', count: summary.value.other_count || 0 },
])

const currentSpecificSourceTitle = computed(() => {
  if (!specificSourceId.value) return '全部群聊与好友'
  return specificSourceTitle.value || hiddenSourcesMap.value[specificSourceId.value] || '指定来源'
})

const filteredAvailableSources = computed(() => {
  const query = sourceSearchQuery.value.trim().toLowerCase()
  const list = availableSources.value || []
  if (!query) return list
  return list.filter(s =>
    (s.source_title || '').toLowerCase().includes(query) ||
    (s.source_id || '').toLowerCase().includes(query)
  )
})

const PAGE_SIZE = 50

const loadHiddenSourcesFromStorage = () => {
  if (typeof window === 'undefined') return
  try {
    const rawIds = localStorage.getItem('wechat_files_hidden_sources')
    if (rawIds) {
      hiddenSourceIds.value = JSON.parse(rawIds) || []
    }
    const rawMap = localStorage.getItem('wechat_files_hidden_sources_map')
    if (rawMap) {
      hiddenSourcesMap.value = JSON.parse(rawMap) || {}
    }
  } catch {}
}

const saveHiddenSourcesToStorage = () => {
  if (typeof window === 'undefined') return
  try {
    localStorage.setItem('wechat_files_hidden_sources', JSON.stringify(hiddenSourceIds.value))
    localStorage.setItem('wechat_files_hidden_sources_map', JSON.stringify(hiddenSourcesMap.value))
  } catch {}
}

const hideSource = (file) => {
  const sid = file?.source_id
  if (!sid) return
  if (!hiddenSourceIds.value.includes(sid)) {
    hiddenSourceIds.value.push(sid)
  }
  const title = file.source_title || sid
  hiddenSourcesMap.value[sid] = title
  saveHiddenSourcesToStorage()

  if (specificSourceId.value === sid) {
    specificSourceId.value = ''
    specificSourceTitle.value = ''
  }

  showToast(`已隐藏「${title}」的文件`, sid)
  void loadItems()
}

const unhideSource = (sid) => {
  hiddenSourceIds.value = hiddenSourceIds.value.filter(id => id !== sid)
  saveHiddenSourcesToStorage()
  void loadItems()
}

const unhideAllSources = () => {
  hiddenSourceIds.value = []
  hiddenSourcesMap.value = {}
  saveHiddenSourcesToStorage()
  hiddenManagerModalOpen.value = false
  void loadItems()
}

const undoHideSource = () => {
  if (toastUndoId.value) {
    unhideSource(toastUndoId.value)
    toastMessage.value = ''
    toastUndoId.value = ''
  }
}

const showToast = (msg, undoId = '') => {
  toastMessage.value = msg
  toastUndoId.value = undoId
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => {
    toastMessage.value = ''
    toastUndoId.value = ''
  }, 4000)
}

const selectSpecificSource = (sid, title = '') => {
  specificSourceId.value = sid || ''
  specificSourceTitle.value = title || ''
  sourceDropdownOpen.value = false
  void loadItems()
}

const clearSpecificSource = () => {
  selectSpecificSource('')
}

const loadItems = async ({ append = false } = {}) => {
  await chatAccounts.ensureLoaded()
  if (!selectedAccount.value) {
    items.value = []
    total.value = 0
    error.value = '未检测到已解密账号，请先选择账号。'
    return
  }

  loading.value = true
  loadingAll.value = false
  error.value = ''
  try {
    const res = await api.listUnifiedFiles({
      account: selectedAccount.value,
      source: sourceFilter.value,
      category: categoryFilter.value,
      keyword: keyword.value,
      source_id: specificSourceId.value || undefined,
      exclude_sources: hiddenSourceIds.value.length ? hiddenSourceIds.value.join(',') : undefined,
      offset: append ? items.value.length : 0,
      limit: PAGE_SIZE,
    })

    const nextItems = Array.isArray(res?.items) ? res.items : []
    items.value = append ? [...items.value, ...nextItems] : nextItems
    total.value = Number(res?.total || 0)
    hasMore.value = items.value.length < total.value
    if (res?.summary && typeof res.summary === 'object') {
      summary.value = res.summary
    }
    if (Array.isArray(res?.available_sources) && res.available_sources.length) {
      availableSources.value = res.available_sources
    }
  } catch (err) {
    error.value = err?.message || '读取文件列表失败'
  } finally {
    loading.value = false
  }
}

const loadAllFiles = async () => {
  await chatAccounts.ensureLoaded()
  if (!selectedAccount.value || loadingAll.value || loading.value) return

  loadingAll.value = true
  error.value = ''
  try {
    const res = await api.listUnifiedFiles({
      account: selectedAccount.value,
      source: sourceFilter.value,
      category: categoryFilter.value,
      keyword: keyword.value,
      source_id: specificSourceId.value || undefined,
      exclude_sources: hiddenSourceIds.value.length ? hiddenSourceIds.value.join(',') : undefined,
      offset: 0,
      limit: 100000,
    })

    const nextItems = Array.isArray(res?.items) ? res.items : []
    items.value = nextItems
    total.value = Number(res?.total || 0)
    hasMore.value = false
    if (res?.summary && typeof res.summary === 'object') {
      summary.value = res.summary
    }
  } catch (err) {
    error.value = err?.message || '读取全部文件失败'
  } finally {
    loadingAll.value = false
  }
}

watch(keyword, () => {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => { void loadItems() }, 250)
})

watch([sourceFilter, categoryFilter], () => {
  void loadItems()
})

watch(selectedAccount, () => {
  void loadItems()
})

const getFileIcon = (file) => {
  const cat = file.category || ''
  const ext = (file.extension || '').toLowerCase()
  if (cat === 'doc') {
    if (['doc', 'docx'].includes(ext)) return 'fa-file-word'
    if (['xls', 'xlsx', 'csv'].includes(ext)) return 'fa-file-excel'
    if (['ppt', 'pptx'].includes(ext)) return 'fa-file-powerpoint'
    if (ext === 'pdf') return 'fa-file-pdf'
    return 'fa-file-lines'
  }
  if (cat === 'video') return 'fa-film'
  if (cat === 'voice') return 'fa-music'
  if (cat === 'image') return 'fa-image'
  if (cat === 'archive') return 'fa-file-zipper'
  return 'fa-file'
}

const getFileIconClass = (file) => {
  const cat = file.category || ''
  const ext = (file.extension || '').toLowerCase()
  if (cat === 'doc') {
    if (['doc', 'docx'].includes(ext)) return 'bg-blue-50 text-blue-600'
    if (['xls', 'xlsx', 'csv'].includes(ext)) return 'bg-emerald-50 text-emerald-600'
    if (['ppt', 'pptx'].includes(ext)) return 'bg-amber-50 text-amber-600'
    if (ext === 'pdf') return 'bg-rose-50 text-rose-600'
    return 'bg-indigo-50 text-indigo-600'
  }
  if (cat === 'video') return 'bg-purple-50 text-purple-600'
  if (cat === 'voice') return 'bg-cyan-50 text-cyan-600'
  if (cat === 'image') return 'bg-teal-50 text-teal-600'
  if (cat === 'archive') return 'bg-amber-50 text-amber-700'
  return 'bg-gray-100 text-gray-600'
}

const openFolder = async (file) => {
  if (!file?.local_path) return
  try {
    await api.openUnifiedFileFolder({
      account: selectedAccount.value,
      id: file.id,
      path: file.local_path,
    })
  } catch (err) {
    alert(err?.message || '无法在访达中定位该文件。')
  }
}

const downloadFile = (file) => {
  if (!file?.id || !selectedAccount.value) return
  const apiBase = useApiBase()
  const url = `${apiBase}/files/download?account=${encodeURIComponent(selectedAccount.value)}&id=${encodeURIComponent(file.id)}`
  window.open(url, '_blank')
}

// Export Modal Logic
const exportModalOpen = ref(false)
const exportMode = ref('folder')
const exportLoading = ref(false)
const exportStatusMessage = ref('')
const exportStatusType = ref('success')

const openExportModal = () => {
  exportModalOpen.value = true
  exportStatusMessage.value = ''
}

const startExport = async () => {
  exportLoading.value = true
  exportStatusMessage.value = ''
  try {
    const res = await api.exportCategorizedFiles({
      account: selectedAccount.value,
      source: sourceFilter.value,
      category: categoryFilter.value,
      keyword: keyword.value,
      source_id: specificSourceId.value || undefined,
      exclude_sources: hiddenSourceIds.value.length ? hiddenSourceIds.value.join(',') : undefined,
      target_mode: exportMode.value,
    })
    exportStatusType.value = 'success'
    exportStatusMessage.value = `分类归档成功！共导出 ${res.exported_count} 个文件 (${res.total_formatted}) 到目录：${res.output_path}`
  } catch (err) {
    exportStatusType.value = 'error'
    exportStatusMessage.value = err?.message || '导出失败，请重试。'
  } finally {
    exportLoading.value = false
  }
}

const handleDocumentClick = (e) => {
  if (sourceDropdownRef.value && !sourceDropdownRef.value.contains(e.target)) {
    sourceDropdownOpen.value = false
  }
}

onMounted(async () => {
  document.addEventListener('click', handleDocumentClick)
  loadHiddenSourcesFromStorage()
  await loadItems()
})

onBeforeUnmount(() => {
  document.removeEventListener('click', handleDocumentClick)
  if (searchTimer) clearTimeout(searchTimer)
  if (toastTimer) clearTimeout(toastTimer)
})
</script>

<style scoped>
.records-page--files {
  background-color: #f7f7f7;
  height: 100%;
}
.file-card {
  transition: all 0.15s ease-in-out;
}
</style>
