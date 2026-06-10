/**
 * QRDrop - Client-side JavaScript
 *
 * Handles multi-file selection, archive downloads, file uploads, and UI interactions.
 * No external dependencies - pure vanilla JavaScript.
 */

(function() {
    'use strict';

    // =============================================
    // Modal focus management + focus trap
    // =============================================

    const FOCUSABLE_SELECTOR = [
        'a[href]',
        'button:not([disabled])',
        'input:not([disabled]):not([type="hidden"])',
        'select:not([disabled])',
        'textarea:not([disabled])',
        '[tabindex]:not([tabindex="-1"])'
    ].join(',');

    // Stack of {element, previouslyFocused, handler} for nested modals.
    const modalStack = [];

    function focusableWithin(root) {
        return Array.from(root.querySelectorAll(FOCUSABLE_SELECTOR))
            .filter(function(el) { return !el.hidden && el.offsetParent !== null; });
    }

    function openModal(element, options) {
        if (!element || modalStack.some(function(m) { return m.element === element; })) return;
        const previouslyFocused = document.activeElement;
        const handler = function(event) {
            if (event.key !== 'Tab') return;
            const focusables = focusableWithin(element);
            if (focusables.length === 0) {
                event.preventDefault();
                return;
            }
            const first = focusables[0];
            const last = focusables[focusables.length - 1];
            if (event.shiftKey && document.activeElement === first) {
                event.preventDefault();
                last.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first.focus();
            }
        };
        document.addEventListener('keydown', handler, true);
        modalStack.push({ element: element, previouslyFocused: previouslyFocused, handler: handler });

        element.hidden = false;
        element.setAttribute('aria-hidden', 'false');
        document.body.style.overflow = 'hidden';

        // Move focus into the dialog.
        const initial = (options && options.initialFocus) || focusableWithin(element)[0] || element;
        // Defer so transitions / display: changes settle before focus.
        requestAnimationFrame(function() { try { initial.focus(); } catch (_) { /* ignore */ } });
    }

    function closeModal(element) {
        const idx = modalStack.findIndex(function(m) { return m.element === element; });
        if (idx === -1) return false;
        const entry = modalStack.splice(idx, 1)[0];
        document.removeEventListener('keydown', entry.handler, true);

        element.hidden = true;
        element.setAttribute('aria-hidden', 'true');
        if (modalStack.length === 0) {
            document.body.style.overflow = '';
        }
        if (entry.previouslyFocused && typeof entry.previouslyFocused.focus === 'function') {
            try { entry.previouslyFocused.focus(); } catch (_) { /* ignore */ }
        }
        return true;
    }

    function topModal() {
        return modalStack.length ? modalStack[modalStack.length - 1].element : null;
    }

    // =============================================
    // App-wide dialog (replaces native confirm/alert)
    // =============================================

    function appDialog(opts) {
        // opts: {title, message, confirmLabel, cancelLabel, danger, alert, prompt, defaultValue}
        // Resolves: confirm/alert -> boolean; prompt -> entered string, or null on cancel.
        return new Promise(function(resolve) {
            const dialog = document.getElementById('app-dialog');
            const titleEl = document.getElementById('app-dialog-title');
            const messageEl = document.getElementById('app-dialog-message');
            const inputEl = document.getElementById('app-dialog-input');
            const confirmBtn = document.getElementById('app-dialog-confirm');
            const cancelBtn = document.getElementById('app-dialog-cancel');
            const isPrompt = !!opts.prompt;

            titleEl.textContent = opts.title || (opts.alert ? 'Notice' : 'Confirm');
            messageEl.textContent = opts.message || '';
            inputEl.hidden = !isPrompt;
            inputEl.value = isPrompt ? (opts.defaultValue || '') : '';
            confirmBtn.textContent = opts.confirmLabel || (opts.alert ? 'OK' : 'Confirm');
            cancelBtn.textContent = opts.cancelLabel || 'Cancel';
            confirmBtn.classList.remove('btn-primary', 'btn-danger');
            confirmBtn.classList.add(opts.danger ? 'btn-danger' : 'btn-primary');
            dialog.classList.toggle('app-dialog-alert', !!opts.alert);

            function cleanup(result) {
                confirmBtn.removeEventListener('click', onConfirm);
                cancelBtn.removeEventListener('click', onCancel);
                dialog.removeEventListener('click', onBackdrop);
                inputEl.removeEventListener('keydown', onInputKey);
                closeModal(dialog);
                resolve(result);
            }
            function onConfirm() { cleanup(isPrompt ? inputEl.value : true); }
            function onCancel() { cleanup(isPrompt ? null : false); }
            function onBackdrop(event) {
                if (event.target.hasAttribute && event.target.hasAttribute('data-dialog-dismiss')) {
                    onCancel();
                }
            }
            function onInputKey(event) {
                if (event.key === 'Enter') {
                    event.preventDefault();
                    onConfirm();
                }
            }

            confirmBtn.addEventListener('click', onConfirm);
            cancelBtn.addEventListener('click', onCancel);
            dialog.addEventListener('click', onBackdrop);
            if (isPrompt) {
                inputEl.addEventListener('keydown', onInputKey);
            }

            openModal(dialog, {
                initialFocus: isPrompt ? inputEl : (opts.alert ? confirmBtn : cancelBtn)
            });
            if (isPrompt) {
                requestAnimationFrame(function() { inputEl.select(); });
            }
        });
    }

    function appConfirm(message, opts) {
        return appDialog(Object.assign({ message: message }, opts || {}));
    }

    function appPrompt(message, opts) {
        return appDialog(Object.assign({ message: message, prompt: true }, opts || {}));
    }

    // =============================================
    // Toast
    // =============================================

    function toast(message, kind, ttlMs) {
        const container = document.getElementById('toast-container');
        if (!container) return;
        const el = document.createElement('div');
        el.className = 'toast' + (kind ? ' toast-' + kind : '');
        el.setAttribute('role', kind === 'error' ? 'alert' : 'status');
        el.textContent = message;
        container.appendChild(el);
        const ttl = typeof ttlMs === 'number' ? ttlMs : 4000;
        setTimeout(function() {
            el.style.opacity = '0';
            el.style.transition = 'opacity 200ms ease';
            setTimeout(function() { el.remove(); }, 220);
        }, ttl);
    }

    // Session storage key for persisting selections
    const STORAGE_KEY = 'qrdrop_selected_paths';

    // Current path from the browse page's data attribute
    function getCurrentPath() {
        const browsePage = document.querySelector('.browse-page');
        return browsePage ? browsePage.dataset.currentPath : '';
    }

    // Selected paths storage
    let selectedPaths = new Set();

    // Load selections from session storage
    function loadSelections() {
        try {
            const stored = sessionStorage.getItem(STORAGE_KEY);
            if (stored) {
                const parsed = JSON.parse(stored);
                if (Array.isArray(parsed)) {
                    selectedPaths = new Set(parsed);
                }
            }
        } catch (e) {
            selectedPaths = new Set();
        }
    }

    // Save selections to session storage
    function saveSelections() {
        try {
            sessionStorage.setItem(STORAGE_KEY, JSON.stringify([...selectedPaths]));
        } catch (e) {
            // Storage might be full or disabled
        }
    }

    // Update UI to reflect current selections
    function updateSelectionUI() {
        const checkboxes = document.querySelectorAll('.file-checkbox');
        const selectionBar = document.getElementById('selection-bar');
        const selectionCount = document.getElementById('selection-count');

        // Update checkbox states
        checkboxes.forEach(function(checkbox) {
            const path = checkbox.dataset.path;
            checkbox.checked = selectedPaths.has(path);
        });

        // Update selection bar visibility and count
        if (selectionBar && selectionCount) {
            const count = selectedPaths.size;
            if (count > 0) {
                selectionBar.hidden = false;
                selectionCount.textContent = count + ' item' + (count === 1 ? '' : 's') + ' selected';
                document.body.classList.add('has-selection');
            } else {
                selectionBar.hidden = true;
                document.body.classList.remove('has-selection');
            }
        }
    }

    // Handle checkbox change
    function handleCheckboxChange(event) {
        const checkbox = event.target;
        const path = checkbox.dataset.path;

        if (checkbox.checked) {
            selectedPaths.add(path);
        } else {
            selectedPaths.delete(path);
        }

        saveSelections();
        updateSelectionUI();
    }

    // Select all items in current view
    function selectAll() {
        const checkboxes = document.querySelectorAll('.file-checkbox');
        checkboxes.forEach(function(checkbox) {
            const path = checkbox.dataset.path;
            selectedPaths.add(path);
        });
        saveSelections();
        updateSelectionUI();
    }

    // Deselect all items
    function selectNone() {
        // Only clear items visible in current view
        const checkboxes = document.querySelectorAll('.file-checkbox');
        checkboxes.forEach(function(checkbox) {
            const path = checkbox.dataset.path;
            selectedPaths.delete(path);
        });
        saveSelections();
        updateSelectionUI();
    }

    // Download selected items as archive
    function downloadArchive() {
        if (selectedPaths.size === 0) {
            return;
        }

        var formatSelect = document.getElementById('archive-format');
        var format = formatSelect ? formatSelect.value : 'zip';

        // Submit a real form into a hidden iframe: the attachment response
        // streams straight to the browser's download manager instead of
        // buffering the whole archive in tab memory. The iframe only ever
        // receives a document when the server responds with an error.
        var iframe = document.getElementById('archive-download-frame');
        if (!iframe) {
            iframe = document.createElement('iframe');
            iframe.id = 'archive-download-frame';
            iframe.name = 'archive-download-frame';
            iframe.hidden = true;
            iframe.addEventListener('load', function() {
                var body = iframe.contentDocument && iframe.contentDocument.body;
                var text = body ? body.textContent.trim() : '';
                if (text) {
                    toast('Could not create archive: ' + text, 'error');
                }
            });
            document.body.appendChild(iframe);
        }

        var form = document.createElement('form');
        form.method = 'post';
        form.action = '/download-archive';
        form.target = 'archive-download-frame';
        form.hidden = true;

        var pathsInput = document.createElement('input');
        pathsInput.type = 'hidden';
        pathsInput.name = 'paths';
        pathsInput.value = JSON.stringify(Array.from(selectedPaths));
        form.appendChild(pathsInput);

        var formatInput = document.createElement('input');
        formatInput.type = 'hidden';
        formatInput.name = 'format';
        formatInput.value = format;
        form.appendChild(formatInput);

        document.body.appendChild(form);
        form.submit();
        form.remove();
    }

    // Delete a file or directory
    function deleteItem(path, name) {
        appConfirm('"' + name + '" will be permanently deleted. This action cannot be undone.', {
            title: 'Delete ' + name + '?',
            confirmLabel: 'Delete',
            danger: true
        }).then(function(ok) {
            if (!ok) return;

            fetch('/delete/' + encodeURIComponent(path), {
                method: 'DELETE',
            })
            .then(function(response) {
                return response.json().then(function(data) {
                    return { ok: response.ok, data: data };
                });
            })
            .then(function(result) {
                if (result.ok && result.data.success) {
                    var row = document.querySelector('.file-row[data-path="' + CSS.escape(path) + '"]');
                    if (row) {
                        row.remove();
                    }
                    selectedPaths.delete(path);
                    saveSelections();
                    updateSelectionUI();
                    toast('Deleted ' + name, 'success');
                } else {
                    toast('Could not delete: ' + (result.data.error || 'Unknown error'), 'error');
                }
            })
            .catch(function(error) {
                toast('Could not delete: ' + error.message, 'error');
            });
        });
    }

    // Initialize delete buttons
    function initDeleteButtons() {
        document.querySelectorAll('.delete-btn').forEach(function(btn) {
            btn.addEventListener('click', function(event) {
                event.stopPropagation();
                var path = btn.dataset.path;
                var name = btn.dataset.name;
                deleteItem(path, name);
            });
        });
    }

    // Create a new folder in the current directory
    function createFolder() {
        appPrompt('Enter a name for the new folder:', {
            title: 'New folder',
            confirmLabel: 'Create'
        }).then(function(name) {
            if (name === null) {
                return;
            }
            name = name.trim();
            if (name === '') {
                return;
            }

            fetch('/mkdir', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    path: getCurrentPath(),
                    name: name,
                }),
            })
            .then(function(response) {
                return response.json().then(function(data) {
                    return { ok: response.ok, data: data };
                });
            })
            .then(function(result) {
                if (result.ok && result.data.success) {
                    // Refresh to show the new folder
                    window.location.reload();
                } else {
                    toast('Could not create folder: ' + (result.data.error || 'Unknown error'), 'error');
                }
            })
            .catch(function(error) {
                toast('Could not create folder: ' + error.message, 'error');
            });
        });
    }

    // Rename a file or directory
    function renameItem(path, name) {
        appPrompt('Rename "' + name + '" to:', {
            title: 'Rename',
            confirmLabel: 'Rename',
            defaultValue: name
        }).then(function(newName) {
            if (newName === null) {
                return;
            }
            newName = newName.trim();
            if (newName === '' || newName === name) {
                return;
            }

            fetch('/rename', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    path: path,
                    new_name: newName,
                }),
            })
            .then(function(response) {
                return response.json().then(function(data) {
                    return { ok: response.ok, data: data };
                });
            })
            .then(function(result) {
                if (result.ok && result.data.success) {
                    // Refresh to show the renamed entry
                    window.location.reload();
                } else {
                    toast('Could not rename: ' + (result.data.error || 'Unknown error'), 'error');
                }
            })
            .catch(function(error) {
                toast('Could not rename: ' + error.message, 'error');
            });
        });
    }

    // Initialize new folder button
    function initNewFolderButton() {
        var newFolderBtn = document.getElementById('new-folder-btn');
        if (newFolderBtn) {
            newFolderBtn.addEventListener('click', createFolder);
        }
    }

    // Initialize rename buttons
    function initRenameButtons() {
        document.querySelectorAll('.rename-btn').forEach(function(btn) {
            btn.addEventListener('click', function(event) {
                event.stopPropagation();
                var path = btn.dataset.path;
                var name = btn.dataset.name;
                renameItem(path, name);
            });
        });
    }

    // Initialize file list functionality
    function initFileList() {
        // Load previous selections
        loadSelections();

        // Attach checkbox listeners
        const checkboxes = document.querySelectorAll('.file-checkbox');
        checkboxes.forEach(function(checkbox) {
            checkbox.addEventListener('change', handleCheckboxChange);
        });

        // Attach select all button
        const selectAllBtn = document.getElementById('select-all-btn');
        if (selectAllBtn) {
            selectAllBtn.addEventListener('click', selectAll);
        }

        // Attach select none button
        const selectNoneBtn = document.getElementById('select-none-btn');
        if (selectNoneBtn) {
            selectNoneBtn.addEventListener('click', selectNone);
        }

        // Attach download archive button
        const downloadArchiveBtn = document.getElementById('download-archive-btn');
        if (downloadArchiveBtn) {
            downloadArchiveBtn.addEventListener('click', downloadArchive);
        }

        // Initialize delete buttons
        initDeleteButtons();

        // Initialize new folder and rename controls
        initNewFolderButton();
        initRenameButtons();

        // Update UI with loaded selections
        updateSelectionUI();
    }

    // Handle row click to toggle checkbox
    function initRowClickHandling() {
        const fileRows = document.querySelectorAll('.file-row');
        fileRows.forEach(function(row) {
            row.addEventListener('click', function(event) {
                // Don't toggle if clicking on a link or the checkbox itself
                if (event.target.tagName === 'A' ||
                    event.target.tagName === 'INPUT' ||
                    event.target.closest('a') ||
                    event.target.closest('button')) {
                    return;
                }

                const checkbox = row.querySelector('.file-checkbox');
                if (checkbox) {
                    checkbox.checked = !checkbox.checked;
                    handleCheckboxChange({ target: checkbox });
                }
            });
        });
    }

    // Initialize keyboard navigation
    function initKeyboardNavigation() {
        document.addEventListener('keydown', function(event) {
            // Ctrl/Cmd + A to select all
            if ((event.ctrlKey || event.metaKey) && event.key === 'a') {
                const fileList = document.querySelector('.file-list');
                if (fileList && document.activeElement.closest('.file-list')) {
                    event.preventDefault();
                    selectAll();
                }
            }

            // Escape: close the topmost modal, otherwise clear file selection.
            if (event.key === 'Escape') {
                const top = topModal();
                if (top) {
                    // If the upload is still in flight, don't let Esc close the upload
                    // modal (matches the "Cancel" button's explicit-action semantics).
                    if (top.id === 'upload-modal' && uploadAbortController) {
                        return;
                    }
                    // The app-dialog cleans up its own listeners via the Cancel button click;
                    // simulate that to keep the resolver path consistent.
                    if (top.id === 'app-dialog') {
                        const cancelBtn = document.getElementById('app-dialog-cancel');
                        if (cancelBtn && !cancelBtn.disabled) {
                            cancelBtn.click();
                            return;
                        }
                    }
                    closeModal(top);
                    return;
                }
                const fileList = document.querySelector('.file-list');
                if (fileList) {
                    selectNone();
                }
            }
        });
    }

    // =============================================
    // Upload Functionality
    // =============================================

    // Upload state
    let uploadAbortController = null;
    let pendingFiles = [];
    let existingFiles = [];

    // Format file size for display
    function formatFileSize(bytes) {
        if (bytes === 0) return '0 B';
        var units = ['B', 'KB', 'MB', 'GB'];
        var i = 0;
        while (bytes >= 1024 && i < units.length - 1) {
            bytes /= 1024;
            i++;
        }
        return bytes.toFixed(i === 0 ? 0 : 1) + ' ' + units[i];
    }

    // Show upload modal
    function showUploadModal() {
        var modal = document.getElementById('upload-modal');
        if (modal) {
            openModal(modal, { initialFocus: document.getElementById('upload-cancel-btn') });
        }
    }

    // Close upload modal (returns true if modal was open)
    function closeUploadModal() {
        var modal = document.getElementById('upload-modal');
        return modal && !modal.hidden ? closeModal(modal) : false;
    }

    // Show overwrite confirmation modal
    function showOverwriteModal(files) {
        var modal = document.getElementById('overwrite-modal');
        var fileList = document.getElementById('overwrite-file-list');
        if (modal && fileList) {
            fileList.innerHTML = files.map(function(f) {
                return '<div class="overwrite-file-item">' + escapeHtml(f) + '</div>';
            }).join('');
            openModal(modal, { initialFocus: document.getElementById('overwrite-cancel-btn') });
        }
    }

    // Close overwrite modal (returns true if modal was open)
    function closeOverwriteModal() {
        var modal = document.getElementById('overwrite-modal');
        return modal && !modal.hidden ? closeModal(modal) : false;
    }

    // Escape HTML for safe display
    function escapeHtml(text) {
        var div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // Update upload progress UI
    function updateUploadProgress(loaded, total, currentFile, fileIndex, totalFiles) {
        var progressBar = document.getElementById('upload-progress-bar');
        var progressText = document.getElementById('upload-progress-text');
        var progressPercent = document.getElementById('upload-progress-percent');

        var percent = total > 0 ? Math.round((loaded / total) * 100) : 0;

        if (progressBar) {
            progressBar.style.width = percent + '%';
        }
        if (progressText) {
            if (currentFile) {
                progressText.textContent = 'Uploading ' + (fileIndex + 1) + ' of ' + totalFiles + ': ' + currentFile;
            } else {
                progressText.textContent = 'Preparing upload...';
            }
        }
        if (progressPercent) {
            progressPercent.textContent = percent + '%';
        }
    }

    // Add file to upload file list UI
    function addFileToUploadList(filename, status, size, errorMessage) {
        var fileList = document.getElementById('upload-file-list');
        if (!fileList) return;

        var statusClass = 'upload-file-' + status;
        var statusIcon = status === 'success' ? '✓' : status === 'error' ? '✗' : status === 'uploading' ? '⏳' : '○';
        var sizeText = size ? ' (' + formatFileSize(size) + ')' : '';
        var errorText = errorMessage
            ? '<span class="upload-file-reason">' + escapeHtml(errorMessage) + '</span>'
            : '';

        var item = document.createElement('div');
        item.className = 'upload-file-item ' + statusClass;
        item.setAttribute('data-filename', filename);
        item.innerHTML = '<span class="upload-file-status">' + statusIcon + '</span>' +
            '<span class="upload-file-name">' + escapeHtml(filename) + sizeText + '</span>' +
            errorText;

        // Check if item already exists and update it
        var existing = fileList.querySelector('[data-filename="' + CSS.escape(filename) + '"]');
        if (existing) {
            existing.className = item.className;
            existing.innerHTML = item.innerHTML;
        } else {
            fileList.appendChild(item);
        }
    }

    // Upload files with progress tracking
    function uploadFiles(files, overwrite) {
        if (!files || files.length === 0) return;

        var currentPath = getCurrentPath();

        // Show upload modal
        showUploadModal();

        // Reset UI
        var fileList = document.getElementById('upload-file-list');
        if (fileList) fileList.innerHTML = '';

        var cancelBtn = document.getElementById('upload-cancel-btn');
        var closeBtn = document.getElementById('upload-close-btn');
        if (cancelBtn) cancelBtn.hidden = false;
        if (closeBtn) closeBtn.hidden = true;

        // Add all files to list as pending
        for (var i = 0; i < files.length; i++) {
            addFileToUploadList(files[i].name, 'pending', files[i].size);
        }

        // Create abort controller
        uploadAbortController = new AbortController();

        // Track overall progress
        var totalSize = 0;
        var uploadedSize = 0;
        for (var j = 0; j < files.length; j++) {
            totalSize += files[j].size;
        }

        // Upload files sequentially
        var fileIndex = 0;
        var failedCount = 0;

        function uploadNextFile() {
            if (fileIndex >= files.length) {
                // All done
                uploadComplete(failedCount, files.length);
                return;
            }

            var file = files[fileIndex];
            addFileToUploadList(file.name, 'uploading', file.size);
            updateUploadProgress(uploadedSize, totalSize, file.name, fileIndex, files.length);

            // Create FormData
            var formData = new FormData();
            formData.append('file', file);
            if (overwrite) {
                formData.append('overwrite', 'true');
            }

            // Build URL with path parameter
            var uploadUrl = '/upload?path=' + encodeURIComponent(currentPath);

            // Use XMLHttpRequest for progress tracking
            var xhr = new XMLHttpRequest();
            xhr.open('POST', uploadUrl, true);

            // Track progress
            xhr.upload.onprogress = function(e) {
                if (e.lengthComputable) {
                    var currentUploaded = uploadedSize + e.loaded;
                    updateUploadProgress(currentUploaded, totalSize, file.name, fileIndex, files.length);
                }
            };

            xhr.onload = function() {
                var response = null;
                try {
                    response = JSON.parse(xhr.responseText);
                } catch (e) {
                    // Non-JSON error body; fall through to the generic message.
                }
                if (xhr.status >= 200 && xhr.status < 300 && response && response.success) {
                    addFileToUploadList(file.name, 'success', file.size);
                    uploadedSize += file.size;
                } else {
                    failedCount++;
                    var reason = (response && response.error) || ('HTTP ' + xhr.status);
                    addFileToUploadList(file.name, 'error', file.size, reason);
                }
                fileIndex++;
                uploadNextFile();
            };

            xhr.onerror = function() {
                failedCount++;
                addFileToUploadList(file.name, 'error', file.size, 'Network error');
                fileIndex++;
                uploadNextFile();
            };

            xhr.onabort = function() {
                addFileToUploadList(file.name, 'error', file.size, 'Cancelled');
                uploadComplete(null, files.length);
            };

            // Store xhr for cancellation
            uploadAbortController.signal.addEventListener('abort', function() {
                xhr.abort();
            });

            xhr.send(formData);
        }

        uploadNextFile();
    }

    // Handle upload completion. failedCount === null means the user cancelled.
    function uploadComplete(failedCount, totalFiles) {
        var cancelBtn = document.getElementById('upload-cancel-btn');
        var closeBtn = document.getElementById('upload-close-btn');
        var progressText = document.getElementById('upload-progress-text');
        var progressPercent = document.getElementById('upload-progress-percent');
        var progressBar = document.getElementById('upload-progress-bar');

        if (cancelBtn) cancelBtn.hidden = true;
        if (closeBtn) closeBtn.hidden = false;

        if (failedCount === null) {
            if (progressText) progressText.textContent = 'Upload cancelled';
        } else if (failedCount > 0) {
            if (progressText) {
                progressText.textContent = failedCount + ' of ' + totalFiles + ' file' +
                    (totalFiles === 1 ? '' : 's') + ' failed';
            }
        } else {
            if (progressText) progressText.textContent = 'Upload complete!';
            if (progressPercent) progressPercent.textContent = '100%';
            if (progressBar) progressBar.style.width = '100%';
        }

        uploadAbortController = null;
    }

    // Check for existing files before upload
    function checkAndUploadFiles(files) {
        if (!files || files.length === 0) return;

        pendingFiles = Array.from(files);
        var currentPath = getCurrentPath();

        // Get filenames
        var filenames = pendingFiles.map(function(f) { return f.name; });

        // Check if files exist
        fetch('/upload-check', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                path: currentPath,
                filenames: filenames,
            }),
        })
        .then(function(response) {
            return response.json().then(function(data) {
                if (!response.ok || !data.success) {
                    throw new Error(data.error || 'Failed to check files');
                }
                return data;
            });
        })
        .then(function(data) {
            // Find existing files
            existingFiles = [];
            for (var filename in data.files) {
                if (data.files[filename].exists) {
                    existingFiles.push(filename);
                }
            }

            if (existingFiles.length > 0) {
                // Show overwrite confirmation
                showOverwriteModal(existingFiles);
            } else {
                // No conflicts, proceed with upload
                uploadFiles(pendingFiles, false);
            }
        })
        .catch(function(error) {
            toast('Error checking files: ' + error.message, 'error');
        });
    }

    // Handle file input change
    function handleFileInputChange(event) {
        var files = event.target.files;
        if (files && files.length > 0) {
            checkAndUploadFiles(files);
        }
        // Reset input so same file can be selected again
        event.target.value = '';
    }

    // Show drag-drop zone
    function showDropzone() {
        var dropzone = document.getElementById('upload-dropzone');
        if (dropzone) {
            dropzone.hidden = false;
        }
    }

    // Hide drag-drop zone
    function hideDropzone() {
        var dropzone = document.getElementById('upload-dropzone');
        if (dropzone) {
            dropzone.hidden = true;
        }
    }

    // Initialize upload functionality
    function initUpload() {
        var uploadBtn = document.getElementById('upload-btn');
        var uploadInput = document.getElementById('upload-input');
        var uploadCancelBtn = document.getElementById('upload-cancel-btn');
        var uploadCloseBtn = document.getElementById('upload-close-btn');
        var uploadModalBackdrop = document.getElementById('upload-modal-backdrop');
        var overwriteCancelBtn = document.getElementById('overwrite-cancel-btn');
        var overwriteSkipBtn = document.getElementById('overwrite-skip-btn');
        var overwriteConfirmBtn = document.getElementById('overwrite-confirm-btn');
        var overwriteModalBackdrop = document.getElementById('overwrite-modal-backdrop');
        var browsePage = document.querySelector('.browse-page');

        // Upload button click
        if (uploadBtn && uploadInput) {
            uploadBtn.addEventListener('click', function() {
                uploadInput.click();
            });
        }

        // File input change
        if (uploadInput) {
            uploadInput.addEventListener('change', handleFileInputChange);
        }

        // Upload modal cancel button
        if (uploadCancelBtn) {
            uploadCancelBtn.addEventListener('click', function() {
                if (uploadAbortController) {
                    uploadAbortController.abort();
                }
                closeUploadModal();
            });
        }

        // Upload modal close button
        if (uploadCloseBtn) {
            uploadCloseBtn.addEventListener('click', function() {
                closeUploadModal();
                // Refresh page to show new files
                window.location.reload();
            });
        }

        // Upload modal backdrop click
        if (uploadModalBackdrop) {
            uploadModalBackdrop.addEventListener('click', function() {
                // Only close if upload is complete
                if (!uploadAbortController) {
                    closeUploadModal();
                    window.location.reload();
                }
            });
        }

        // Overwrite modal cancel button
        if (overwriteCancelBtn) {
            overwriteCancelBtn.addEventListener('click', function() {
                closeOverwriteModal();
                pendingFiles = [];
                existingFiles = [];
            });
        }

        // Overwrite modal skip button
        if (overwriteSkipBtn) {
            overwriteSkipBtn.addEventListener('click', function() {
                closeOverwriteModal();
                // Filter out existing files
                var existingSet = new Set(existingFiles);
                var filesToUpload = pendingFiles.filter(function(f) {
                    return !existingSet.has(f.name);
                });
                pendingFiles = [];
                existingFiles = [];
                if (filesToUpload.length > 0) {
                    uploadFiles(filesToUpload, false);
                }
            });
        }

        // Overwrite modal confirm button
        if (overwriteConfirmBtn) {
            overwriteConfirmBtn.addEventListener('click', function() {
                closeOverwriteModal();
                var filesToUpload = pendingFiles;
                pendingFiles = [];
                existingFiles = [];
                uploadFiles(filesToUpload, true);
            });
        }

        // Overwrite modal backdrop click
        if (overwriteModalBackdrop) {
            overwriteModalBackdrop.addEventListener('click', function() {
                closeOverwriteModal();
                pendingFiles = [];
                existingFiles = [];
            });
        }

        // Drag and drop handling
        if (browsePage) {
            var dragCounter = 0;

            browsePage.addEventListener('dragenter', function(event) {
                event.preventDefault();
                event.stopPropagation();
                dragCounter++;
                if (event.dataTransfer && event.dataTransfer.types.indexOf('Files') !== -1) {
                    showDropzone();
                }
            });

            browsePage.addEventListener('dragleave', function(event) {
                event.preventDefault();
                event.stopPropagation();
                dragCounter--;
                if (dragCounter <= 0) {
                    dragCounter = 0;
                    hideDropzone();
                }
            });

            browsePage.addEventListener('dragover', function(event) {
                event.preventDefault();
                event.stopPropagation();
            });

            browsePage.addEventListener('drop', function(event) {
                event.preventDefault();
                event.stopPropagation();
                dragCounter = 0;
                hideDropzone();

                var files = event.dataTransfer && event.dataTransfer.files;
                if (files && files.length > 0) {
                    checkAndUploadFiles(files);
                }
            });

            // Handle drag events on dropzone itself
            var dropzone = document.getElementById('upload-dropzone');
            if (dropzone) {
                dropzone.addEventListener('dragover', function(event) {
                    event.preventDefault();
                    event.stopPropagation();
                });

                dropzone.addEventListener('drop', function(event) {
                    event.preventDefault();
                    event.stopPropagation();
                    dragCounter = 0;
                    hideDropzone();

                    var files = event.dataTransfer && event.dataTransfer.files;
                    if (files && files.length > 0) {
                        checkAndUploadFiles(files);
                    }
                });
            }
        }
    }

    // Initialize when DOM is ready
    function init() {
        // Only initialize on browse pages
        if (document.querySelector('.browse-page')) {
            initFileList();
            initRowClickHandling();
            initKeyboardNavigation();
            initUpload();
        }
    }

    // Run initialization
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
