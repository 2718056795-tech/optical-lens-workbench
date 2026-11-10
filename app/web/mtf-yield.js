(() => {
  const maxFileBytes = 4 * 1024 * 1024;
  const palette = ['#0064d6', '#b84309', '#087b55', '#8053bd', '#b43266', '#277483', '#7b5c17', '#3a5d9a', '#588230', '#a53a35', '#6b57a1', '#47687c'];
  const svgNamespace = 'http://www.w3.org/2000/svg';

  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text) element.textContent = text;
    if (className) element.className = className;
    return element;
  }

  function svgNode(tag, attributes, text) {
    const element = document.createElementNS(svgNamespace, tag);
    for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, value);
    if (text) element.textContent = text;
    return element;
  }

  function readReport(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve({name: file.name, data: String(reader.result)});
      reader.onerror = () => reject(new Error(`无法读取 ${file.name}`));
      reader.onabort = reader.onerror;
      reader.readAsDataURL(file);
    });
  }

  const colorOf = curve => curve.is_min ? '#151719' : palette[(Math.max(1, curve.field) - 1) % palette.length];
  const curveLabel = curve => curve.label.includes('80%') ? curve.label : `${curve.label} · 80% > ${curve.mtf80.toFixed(3)}`;

  function validateResult(data) {
    // V6's spline can leave round-off immediately below 0% or above 100%.
    const validSeries = (values, min, max) => Array.isArray(values) && values.every(value => Number.isFinite(value) && value >= min - 1e-9 && value <= max + 1e-9);
    if (!validSeries(data.thresholds, 0, 1) || !data.thresholds.length || !Array.isArray(data.curves) || !data.curves.length ||
        data.curves.some(curve => !validSeries(curve.values, 0, 100) || curve.values.length !== data.thresholds.length || !Number.isFinite(curve.mtf80))) {
      throw new Error('良率曲线数据不完整，请重新计算。');
    }
  }

  function mount(parent) {
    const host = node('div', '', 'mtf-yield');
    host.id = 'mtfYieldPanel';
    host.hidden = true;
    host.innerHTML = `
      <form class="mtf-yield-controls plotcard">
        <div class="mtf-yield-import">
          <input id="mtfYieldFiles" type="file" accept=".txt,text/plain" multiple hidden>
          <button type="button" data-report-picker="mtfYieldFiles">导入 TXT</button>
          <div class="mtf-yield-file" hidden>
            <span id="mtfYieldName" class="mtf-yield-filename"></span>
            <button class="mtf-yield-remove" type="button" aria-label="移除第一份 TXT">×</button>
          </div>
          <div class="mtf-yield-file" hidden>
            <span id="mtfYieldName2" class="mtf-yield-filename"></span>
            <button class="mtf-yield-remove" type="button" aria-label="移除第二份 TXT">×</button>
          </div>
        </div>
        <div class="mtf-yield-actions">
          <label class="chk"><input id="mtfYieldMin" type="checkbox">显示最差视场</label>
          <button id="mtfYieldCalculate" type="submit" disabled>计算良率</button>
        </div>
      </form>
      <p id="mtfYieldStatus" role="status" aria-live="polite">可一次选择 1–2 份 TXT，同频的子午和弧矢报告可同图查看。</p>
      <section class="mtf-yield-result plotcard" hidden aria-labelledby="mtfYieldTitle">
        <div class="mtf-yield-heading"><h3 id="mtfYieldTitle">MTF 良率</h3><span>子午实线 · 弧矢虚线</span></div>
        <ul class="mtf-yield-warnings" hidden></ul>
        <svg id="mtfYieldPlot" role="img" aria-label="MTF 阈值与通过率，横轴从 1 降到 0"></svg>
        <div id="mtfYieldLegend" class="mtf-yield-legend" role="group" aria-label="显示或隐藏曲线"></div>
        <ul class="mtf-yield-reports" aria-label="报告信息"></ul>
      </section>`;
    parent.append(host);

    const form = host.querySelector('form');
    const input = form.querySelector('#mtfYieldFiles');
    const picker = form.querySelector('[data-report-picker]');
    const fileSlots = [...form.querySelectorAll('.mtf-yield-file')];
    const filenames = [...form.querySelectorAll('.mtf-yield-filename')];
    const removeButtons = [...form.querySelectorAll('.mtf-yield-remove')];
    const showMin = form.querySelector('#mtfYieldMin');
    const start = form.querySelector('[type="submit"]');
    const status = host.querySelector('#mtfYieldStatus');
    const emptyStatus = status.textContent;
    const result = host.querySelector('.mtf-yield-result');
    const chart = host.querySelector('svg');
    const legend = host.querySelector('#mtfYieldLegend');
    const reports = host.querySelector('.mtf-yield-reports');
    const warnings = host.querySelector('.mtf-yield-warnings');
    const hidden = new Set(), paths = new Map();
    let selectedFiles = [], data = null, busy = false;

    function showStatus(text, error = false) {
      status.textContent = text;
      status.classList.toggle('error', error);
    }

    function draw() {
      if (!data || !chart.clientWidth || !chart.clientHeight) return;
      const width = chart.clientWidth, height = chart.clientHeight;
      const left = 54, right = width - 15, top = 12, bottom = height - 45;
      const x = value => left + (1 - value) * (right - left);
      const y = value => bottom - Math.max(0, Math.min(100, value)) / 100 * (bottom - top);
      chart.setAttribute('viewBox', `0 0 ${width} ${height}`);
      const plot = document.createDocumentFragment();
      for (let tick = 0; tick <= 10; tick++) {
        const percent = tick * 10, px = x(tick / 10), py = y(percent);
        if (width >= 420 || tick % 2 === 0) {
          plot.append(svgNode('line', {x1: px, x2: px, y1: top, y2: bottom, class: 'mtf-yield-grid'}),
            svgNode('text', {x: px, y: bottom + 18, 'text-anchor': 'middle'}, (tick / 10).toFixed(1)));
        }
        plot.append(svgNode('line', {x1: left, x2: right, y1: py, y2: py, class: 'mtf-yield-grid'}),
          svgNode('text', {x: left - 6, y: py + 4, 'text-anchor': 'end'}, `${percent}%`));
      }
      plot.append(svgNode('path', {d: `M${left} ${top}V${bottom}H${right}`, class: 'mtf-yield-axis'}),
        svgNode('text', {x: (left + right) / 2, y: height - 6, 'text-anchor': 'middle'}, 'MTF 阈值'),
        svgNode('text', {transform: `translate(12 ${(top + bottom) / 2}) rotate(-90)`, 'text-anchor': 'middle'}, '通过率'));
      paths.clear();
      for (const curve of data.curves) {
        const points = data.thresholds.map((threshold, i) => `${i ? 'L' : 'M'}${x(threshold).toFixed(2)},${y(curve.values[i]).toFixed(2)}`).join('');
        const path = svgNode('path', {d: points, stroke: colorOf(curve), fill: 'none', 'stroke-width': curve.is_min ? 2.6 : 1.7,
          'stroke-dasharray': curve.direction === 'SAG' ? '6 4' : 'none', 'data-curve-id': curve.id, 'data-direction': curve.direction});
        if (curve.is_min) path.classList.add('mtf-yield-minimum');
        if (hidden.has(curve.id)) path.style.display = 'none';
        path.append(svgNode('title', {}, curveLabel(curve)));
        paths.set(curve.id, path);
        plot.append(path);
      }
      chart.replaceChildren(plot);
    }

    function render(payload) {
      validateResult(payload);
      data = payload;
      hidden.clear();
      legend.replaceChildren();
      for (const curve of payload.curves) {
        const button = node('button', '', 'mtf-yield-curve');
        if (curve.is_min) button.classList.add('mtf-yield-minimum');
        const swatch = node('span', '', 'mtf-yield-swatch');
        swatch.setAttribute('aria-hidden', 'true');
        swatch.style.borderColor = colorOf(curve);
        swatch.classList.toggle('sag', curve.direction === 'SAG');
        button.append(swatch, node('span', curveLabel(curve)));
        button.type = 'button';
        button.dataset.curveId = curve.id;
        button.dataset.direction = curve.direction;
        button.setAttribute('aria-pressed', 'true');
        button.onclick = () => {
          const showing = hidden.delete(curve.id);
          if (!showing) hidden.add(curve.id);
          button.setAttribute('aria-pressed', String(showing));
          const path = paths.get(curve.id);
          if (path) path.style.display = showing ? '' : 'none';
        };
        legend.append(button);
      }
      reports.replaceChildren(...payload.reports.map(report => {
        const frequency = Number.isFinite(report.frequency_lp_mm) ? `${report.frequency_lp_mm} lp/mm` : '频率未标记';
        const configuration = report.configuration == null ? '' : ` · 结构 ${report.configuration}`;
        const info = `${report.direction} · ${frequency}${configuration} · ${report.field_count} 视场 · ${report.sample_count} 样本`;
        const item = node('li');
        item.append(node('strong', report.name), node('span', info));
        return item;
      }));
      warnings.replaceChildren(...payload.warnings.map(text => node('li', text)));
      warnings.hidden = !payload.warnings.length;
      result.hidden = false;
      draw();
    }

    function updateControls() {
      start.disabled = busy || !selectedFiles.length;
      for (const control of [picker, input, ...removeButtons]) control.disabled = busy;
      fileSlots.forEach((slot, index) => {
        const file = selectedFiles[index];
        filenames[index].textContent = file?.name || '';
        slot.hidden = !file;
      });
    }

    async function run() {
      const files = selectedFiles;
      if (busy || !files.length) return;
      busy = true;
      updateControls();
      result.hidden = true;
      showStatus('正在读取 TXT 并计算良率…');
      try {
        const reports = await Promise.all(files.map(readReport));
        const payload = await postJson('/api/mtf-yield', {files: reports, include_min: true});
        render(payload);
        showStatus(`已计算 ${payload.reports.length} 份 TXT 报告。`);
      } catch (error) {
        showStatus(`计算失败：${error.message}`, true);
      } finally {
        busy = false;
        updateControls();
      }
    }

    function invalidateResult() {
      data = null;
      result.hidden = true;
      updateControls();
      showStatus(selectedFiles.length ? '已选文件，点击「计算良率」。' : emptyStatus);
    }

    picker.onclick = () => input.click();
    input.onchange = () => {
      const files = [...input.files];
      input.value = '';
      if (!files.length) return;
      if (files.length > fileSlots.length) {
        showStatus('最多导入两份 TXT，请重新选择。', true);
        return;
      }
      const oversized = files.find(file => file.size > maxFileBytes);
      if (oversized) {
        showStatus(`${oversized.name} 超过 4 MiB。`, true);
        return;
      }
      if (files.length === 1 && selectedFiles.length === fileSlots.length) {
        showStatus('已导入两份 TXT，请先移除一份，或一次选择两份替换。', true);
        return;
      }
      selectedFiles = files.length === 1 ? [...selectedFiles, ...files] : files;
      invalidateResult();
    };
    removeButtons.forEach((button, index) => {
      button.onclick = () => {
        selectedFiles.splice(index, 1);
        invalidateResult();
        picker.focus();
      };
    });
    showMin.onchange = () => host.classList.toggle('show-worst-field', showMin.checked);
    showMin.onchange();
    form.onsubmit = event => { event.preventDefault(); run(); };
    new ResizeObserver(draw).observe(chart);
    return {host, run};
  }

  window.mtfYield = {mount};
})();
