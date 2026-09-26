(function () {
  if (window.ContextHelpTour) return;

  const fab = document.getElementById('helpTourFab');
  const layer = document.getElementById('helpTourLayer');
  const spotlight = document.getElementById('helpTourSpotlight');
  const card = document.getElementById('helpTourCard');
  const title = document.getElementById('helpTourTitle');
  const text = document.getElementById('helpTourText');
  const context = document.getElementById('helpTourContext');
  const counter = document.getElementById('helpTourCounter');
  const dots = document.getElementById('helpTourDots');
  const prevButton = document.getElementById('helpTourPrev');
  const nextButton = document.getElementById('helpTourNext');
  const skipButton = document.getElementById('helpTourSkip');
  const closeButton = document.getElementById('helpTourClose');

  if (!fab || !layer || !spotlight || !card) return;

  let activeSteps = [];
  let stepIndex = 0;
  let activeTarget = null;
  let open = false;
  let repositionTimer = 0;
  let previousFocusedElement = null;

  const pageTours = {
    projects: {
      label: 'Bộ thời khóa biểu',
      steps: [
        { target: '.page-title', title: 'Quản lý các bộ thời khóa biểu', text: 'Đây là nơi tạo và quản lý các phương án thời khóa biểu của trường.' },
        { target: '.page-title .btn', title: 'Tạo bộ thời khóa biểu mới', text: 'Bấm “Tạo mới” để khai báo tên bộ, trường, số ngày học, số buổi và số tiết mỗi buổi.' },
        { target: '.project-grid', title: 'Danh sách các bộ hiện có', text: 'Mỗi thẻ là một bộ thời khóa biểu độc lập. Bạn có thể mở, đổi tên, nhân bản hoặc xóa bộ tại đây.' },
        { target: '.project-card .row', title: 'Thao tác nhanh với một bộ', text: 'Mở bộ để cấu hình dữ liệu và xếp lịch; nhân bản khi muốn tạo một phương án mới từ dữ liệu hiện có.' },
        { target: 'a[href="/schedule-audit"]', title: 'Import và kiểm tra TKB', text: 'Dùng chức năng này khi bạn có file thời khóa biểu bên ngoài và muốn kiểm tra lỗi hoặc xung đột.' }
      ]
    },
    users: {
      label: 'Quản lý tài khoản',
      steps: [
        { target: '.page-title', title: 'Quản lý người dùng và trường', text: 'Trang này tập trung các thao tác quản trị tài khoản giáo viên, quản trị viên và trường học.' },
        { target: '.school-create-form', title: 'Tạo trường', text: 'Tạo trường mới trước khi gán quản trị viên hoặc tạo bộ thời khóa biểu cho trường đó.' },
        { target: 'main .panel', title: 'Quản lý danh sách trường', text: 'Bạn có thể xem và đổi tên các trường đã có trong hệ thống.' },
        { target: '.project-grid', title: 'Quản lý tài khoản', text: 'Mỗi thẻ tài khoản cho phép xem trạng thái, gán trường và cập nhật quyền hoặc thông tin cần thiết.' },
        { target: '#chatbot-logs', title: 'Nhật ký Trợ lý AI', text: 'Khu vực này cho phép quản trị viên theo dõi lịch sử sử dụng Trợ lý AI và dọn nhật ký khi cần.' }
      ]
    },
    audit: {
      label: 'Import & kiểm tra TKB',
      steps: [
        { target: '#audit .section-head', title: 'Kiểm tra thời khóa biểu từ file', text: 'Trang này dùng để đưa một thời khóa biểu bên ngoài vào hệ thống và kiểm tra các vấn đề có thể xảy ra.' },
        { target: '#scheduleAuditDropzone', title: 'Chọn file cần kiểm tra', text: 'Kéo thả hoặc bấm vào vùng này để chọn file Excel, Word, CSV hoặc TSV.' },
        { target: '.schedule-audit-upload-card', title: 'Chạy kiểm tra', text: 'Sau khi chọn file, các nút kiểm tra sẽ xuất hiện để bạn bắt đầu phân tích dữ liệu.' },
        { target: '#scheduleAuditAiResult', title: 'Phân tích bằng AI', text: 'Nếu sử dụng phân tích AI, phần giải thích và gợi ý sẽ được hiển thị tại khu vực này.' },
        { target: '#scheduleAuditResult', title: 'Kết quả kiểm tra', text: 'Các lỗi, cảnh báo và thông tin chi tiết của thời khóa biểu sẽ được tổng hợp ở đây.' }
      ]
    },
    teacherPortal: {
      label: 'Cổng giáo viên',
      steps: [
        { target: 'main .section-head', title: 'Thời khóa biểu dành cho giáo viên', text: 'Bạn có thể xem lịch hiện tại và chuyển nhanh giữa các bộ thời khóa biểu được cấp quyền.' },
        { target: '#teacherProjectSelect', title: 'Chọn bộ thời khóa biểu', text: 'Chuyển sang một bộ khác khi tài khoản của bạn được quyền xem nhiều phương án.' },
        { target: '#viewType', title: 'Đổi cách xem', text: 'Lọc lịch theo toàn trường, giáo viên, lớp hoặc môn học để tìm đúng thông tin cần xem.' },
        { target: '#viewSearch', title: 'Tìm nhanh', text: 'Nhập tên giáo viên, lớp hoặc môn để thu hẹp danh sách và mở đúng lịch.' },
        { target: '#scheduleGrid', title: 'Khu vực thời khóa biểu', text: 'Lịch sau khi lọc sẽ hiển thị tại đây. Đây là chế độ xem, không làm thay đổi lịch của nhà trường.' },
        { target: '#teacher-preferences', title: 'Gửi nguyện vọng', text: 'Bạn có thể gửi các khung giờ mong muốn hoặc muốn tránh để quản trị viên tham khảo.' },
        { target: '#teacherPreferenceGrid', title: 'Chọn khung giờ nguyện vọng', text: 'Bấm một ô để chuyển lần lượt giữa Không chọn, Mong muốn và Muốn tránh.' },
        { target: '.preference-form .row.end .btn', title: 'Gửi cho quản trị viên', text: 'Bấm “Gửi nguyện vọng” sau khi chọn khung giờ và nhập ghi chú nếu cần.' }
      ]
    },
    teacherAccount: {
      label: 'Tài khoản giáo viên',
      steps: [
        { target: 'main .section-head', title: 'Thông tin tài khoản', text: 'Trang này dùng để xem và cập nhật các thông tin liên quan đến tài khoản giáo viên.' },
        { target: 'main .account-form', title: 'Thông tin cá nhân', text: 'Kiểm tra hoặc cập nhật các trường thông tin được hệ thống cho phép chỉnh sửa.' },
        { target: 'form.account-form', title: 'Đổi mật khẩu', text: 'Dùng biểu mẫu này để đặt mật khẩu mới cho tài khoản khi cần.' }
      ]
    },
    teacherEmpty: {
      label: 'Cổng giáo viên',
      steps: [
        { target: 'main .section-head', title: 'Chưa có thời khóa biểu để hiển thị', text: 'Tài khoản đang chưa có bộ thời khóa biểu phù hợp để xem.' },
        { target: '#teacherProjectSelect', title: 'Danh sách bộ thời khóa biểu', text: 'Khi quản trị viên cấp quyền cho một bộ thời khóa biểu, bạn sẽ có thể chọn và xem bộ đó tại đây.' }
      ]
    }
  };

  const workspaceTours = {
    overview: {
      label: 'Tổng quan',
      steps: [
        { target: '.sidebar', title: 'Danh mục quản lý', text: 'Dùng thanh này để chuyển giữa dữ liệu môn học, giáo viên, lớp, phân công, ràng buộc và khu vực xếp lịch.' },
        { target: '#overview .page-title', title: 'Thông tin bộ thời khóa biểu', text: 'Phần đầu cho biết tên bộ, trường và cấu hình số ngày, số buổi của phương án hiện tại.' },
        { target: '#overview .stats', title: 'Theo dõi nhanh dữ liệu', text: 'Các thẻ thống kê giúp bạn biết ngay số giáo viên, lớp, phân công và số tiết đã được xếp.' },
        { target: '#overview [data-schedule-action]', title: 'Xếp tự động', text: 'Sau khi dữ liệu và ràng buộc đã đủ, bấm nút này để hệ thống tạo thời khóa biểu tự động.' }
      ]
    },
    subjects: entitySteps('Môn học', '#subjects', '#subjectTable', 'môn', 'Khai báo tên môn, tên rút gọn và giới hạn số tiết liên tiếp.'),
    departments: entitySteps('Tổ chuyên môn', '#departments', '#departmentTable', 'tổ', 'Nhóm giáo viên theo chuyên môn để dữ liệu quản lý rõ ràng hơn.'),
    teachers: entitySteps('Giáo viên', '#teachers', '#teacherTable', 'giáo viên', 'Quản lý giáo viên, tải dạy và tổ chuyên môn trước khi tạo phân công.'),
    grades: entitySteps('Khối / nhóm lớp', '#grades', '#gradeTable', 'khối', 'Thiết lập khối và chương trình chuẩn để kiểm tra phân công thiếu hoặc sai.'),
    classes: entitySteps('Lớp học', '#classes', '#classTable', 'lớp', 'Tạo các lớp và gắn từng lớp vào khối tương ứng.'),
    assignments: {
      label: 'Phân công',
      steps: [
        { target: '#assignments .section-head', title: 'Phân công giảng dạy', text: 'Mỗi phân công xác định giáo viên, lớp, môn và số tiết phải dạy trong một tuần.' },
        { target: '#assignments .section-head .btn', title: 'Thêm phân công', text: 'Bấm vào đây để tạo một phân công mới. Hệ thống sẽ dùng các phân công này làm đầu vào khi xếp lịch.' },
        { target: '.assignment-explanation', title: 'Hiểu đúng số tiết', text: 'Phần giải thích này giúp phân biệt số buổi/ngày, tiết/tuần và giới hạn tiết/ngày của giáo viên.' },
        { target: '.assignment-filter-panel', title: 'Lọc và kiểm tra phân công', text: 'Lọc theo lớp, môn, giáo viên hoặc trạng thái để nhanh chóng tìm các phân công cần xử lý.' },
        { target: '#assignmentCompletenessSummary', title: 'Kiểm tra độ đầy đủ', text: 'Khu vực này đối chiếu phân công hiện tại với chương trình chuẩn của lớp và khối.' },
        { target: '#assignmentTable', title: 'Danh sách phân công', text: 'Xem, sửa hoặc xóa các phân công hiện có tại bảng này.' }
      ]
    },
    constraints: {
      label: 'Ràng buộc',
      steps: [
        { target: '#constraints .section-head', title: 'Ngày nghỉ / tiết tránh', text: 'Ràng buộc ở đây là điều kiện cứng: các ô được đánh dấu sẽ không được hệ thống xếp tiết vào.' },
        { target: '#constraintType', title: 'Chọn loại đối tượng', text: 'Chọn đang thiết lập tiết tránh cho giáo viên hay cho lớp.' },
        { target: '#constraintEntity', title: 'Chọn giáo viên hoặc lớp', text: 'Chọn đúng đối tượng cần cấu hình trước khi đánh dấu các ô không thể học hoặc dạy.' },
        { target: '#constraintGrid', title: 'Đánh dấu tiết cần tránh', text: 'Bấm vào các ô thời gian không được phép xếp lịch cho đối tượng đang chọn.' },
        { target: '.constraint-toolbar .btn', title: 'Lưu ràng buộc', text: 'Nhớ lưu sau khi thay đổi. Nếu rời trang khi chưa lưu, các thay đổi có thể bị bỏ.' }
      ]
    },
    preferences: {
      label: 'Nguyện vọng',
      steps: [
        { target: '#preferences .section-head', title: 'Nguyện vọng giáo viên', text: 'Đây là các đề xuất do giáo viên gửi để quản trị viên tham khảo.' },
        { target: '#preferenceInbox', title: 'Hộp nguyện vọng', text: 'Xem nội dung, thời gian và trạng thái của từng nguyện vọng tại đây.' },
        { target: '#preferences .preference-head-actions', title: 'Quản lý nguyện vọng', text: 'Bạn có thể mở trang đăng ký giáo viên hoặc xóa toàn bộ nguyện vọng khi cần.' }
      ]
    },
    schedule: {
      label: 'Xếp & tinh chỉnh',
      steps: [
        { target: '#schedule .section-head', title: 'Khu vực xếp thời khóa biểu', text: 'Đây là nơi tạo lịch tự động, lọc lịch và tinh chỉnh từng tiết bằng thao tác trực tiếp.' },
        { target: '#viewType', title: 'Chọn kiểu xem', text: 'Chuyển giữa xem tổng quát, theo lớp, theo giáo viên hoặc theo môn học.' },
        { target: '#viewSearch', title: 'Tìm đối tượng', text: 'Nhập tên lớp, giáo viên hoặc môn để mở nhanh đúng lịch cần kiểm tra.' },
        { target: '#assignmentCoverage', title: 'Độ phủ phân công', text: 'Khu vực này cho biết các phân công đã được xếp đủ hay còn thiếu tiết.' },
        { target: '.manual-tray-panel', title: 'Kho tiết chưa xếp', text: 'Các tiết chưa có vị trí hoặc được thu hồi sẽ nằm trong khay. Chọn một thẻ rồi bấm ô đích để xếp thủ công.' },
        { target: '#scheduleGrid', title: 'Lưới thời khóa biểu', text: 'Bấm tiết trên lịch để chọn, sau đó bấm ô hợp lệ để chuyển. Hệ thống sẽ kiểm tra các điều kiện trước khi lưu.' },
        { target: '#schedule [data-schedule-action]', title: 'Xếp tự động', text: 'Bấm nút này để chạy solver và tạo lại lịch từ dữ liệu phân công cùng các ràng buộc hiện tại.' }
      ]
    }
  };

  function entitySteps(label, sectionSelector, tableSelector, noun, description) {
    return {
      label,
      steps: [
        { target: `${sectionSelector} .section-head`, title: label, text: description },
        { target: `${sectionSelector} .section-head .btn`, title: `Thêm ${noun}`, text: `Bấm vào đây để tạo ${noun} mới cho bộ thời khóa biểu.` },
        { target: tableSelector, title: `Danh sách ${noun}`, text: `Các ${noun} hiện có được hiển thị tại đây. Bạn có thể sử dụng các thao tác trong bảng để cập nhật dữ liệu.` }
      ]
    };
  }

  function detectTour() {
    const activeWorkspaceTab = document.querySelector('.workspace .nav.active[data-tab]')?.dataset.tab;
    if (activeWorkspaceTab && workspaceTours[activeWorkspaceTab]) return workspaceTours[activeWorkspaceTab];
    if (document.querySelector('.workspace')) return workspaceTours.overview;
    if (document.getElementById('audit') && document.getElementById('scheduleAuditDropzone')) return pageTours.audit;
    if (document.getElementById('teacher-preferences')) return pageTours.teacherPortal;
    if (document.querySelector('main.account-page')) return pageTours.teacherAccount;
    if (document.querySelector('main.preference-page') && document.getElementById('teacherProjectSelect')?.disabled) return pageTours.teacherEmpty;
    if (document.getElementById('chatbot-logs')) return pageTours.users;
    if (document.getElementById('newProject') && document.querySelector('.project-grid')) return pageTours.projects;

    return {
      label: 'Hướng dẫn trang này',
      steps: [
        { target: '.appbar', title: 'Thanh điều hướng', text: 'Dùng thanh phía trên để truy cập các chức năng chính và tài khoản.' },
        { target: 'main', title: 'Nội dung chính', text: 'Các chức năng và dữ liệu của trang hiện tại được hiển thị trong khu vực này.' }
      ]
    };
  }

  function resolveTarget(step) {
    if (!step) return null;
    if (step.element instanceof Element) return step.element;
    if (!step.target) return null;
    try {
      const candidates = [...document.querySelectorAll(step.target)];
      return candidates.find(isUsableTarget) || candidates[0] || null;
    } catch (_) {
      return null;
    }
  }

  function isUsableTarget(element) {
    if (!(element instanceof Element)) return false;
    const style = window.getComputedStyle(element);
    if (style.display === 'none' || style.visibility === 'hidden') return false;
    const rect = element.getBoundingClientRect();
    return rect.width > 1 && rect.height > 1;
  }

  function prepareSteps(tour) {
    return (tour?.steps || []).map(step => ({ ...step, element: resolveTarget(step) })).filter(step => isUsableTarget(step.element));
  }

  function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  async function closeOtherFloatingPanels() {
    if (window.GeneralChat?.isOpen?.()) {
      if (window.GeneralChat.closeWithoutUndock) {
        window.GeneralChat.closeWithoutUndock();
      } else {
        await window.GeneralChat.close();
      }
    }
    if (window.ChatbotAssistant?.isOpen?.()) {
      if (window.ChatbotAssistant.closeWithoutUndock) {
        window.ChatbotAssistant.closeWithoutUndock();
      } else {
        await window.ChatbotAssistant.close();
      }
    }
  }

  async function start() {
    if (open || window.FabMotion?.isAnimating?.()) return;
    await closeOtherFloatingPanels();

    const tour = detectTour();
    const steps = prepareSteps(tour);
    if (!steps.length) return;

    previousFocusedElement = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    activeSteps = steps;
    stepIndex = 0;
    open = true;
    context.textContent = tour.label || 'Hướng dẫn';
    fab.setAttribute('aria-expanded', 'true');
    fab.classList.add('is-glowing');

    document.getElementById('generalChatFab')?.classList.remove('is-glowing');
    document.getElementById('chatbotFab')?.classList.remove('is-glowing');

    if (window.FabMotion) {
      await window.FabMotion.open(fab, null, {
        onOpened: () => {
          layer.hidden = false;
          layer.setAttribute('aria-hidden', 'false');
          requestAnimationFrame(() => layer.classList.add('is-open'));
          document.documentElement.classList.add('help-tour-active');
        }
      });
      await showStep(0, true);
      requestAnimationFrame(() => card.focus({ preventScroll: true }));
    } else {
      fab.classList.add('is-launching');
      window.FabMotion?.startGhostTrail?.([fab], 360, {
        gradient: 'linear-gradient(135deg, #38bdf8 0%, #6366f1 52%, #a855f7 100%)',
        glow: 'rgba(99, 102, 241, .7)',
        borderGlow: '#c7d2fe'
      });

      await sleep(window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 180);
      fab.classList.remove('is-launching');
      layer.hidden = false;
      layer.setAttribute('aria-hidden', 'false');
      requestAnimationFrame(() => layer.classList.add('is-open'));
      document.documentElement.classList.add('help-tour-active');
      await showStep(0, true);
      requestAnimationFrame(() => card.focus({ preventScroll: true }));
    }
  }

  async function closeTour(completed = false) {
    if (!open) return;
    if (completed) burstAtFab();
    open = false;
    activeTarget = null;
    layer.classList.remove('is-open');
    layer.setAttribute('aria-hidden', 'true');
    fab.setAttribute('aria-expanded', 'false');
    fab.classList.remove('is-glowing');
    document.documentElement.classList.remove('help-tour-active');
    clearTimeout(repositionTimer);
    setTimeout(() => {
      if (!open) layer.hidden = true;
    }, 240);

    if (window.FabMotion) {
      await window.FabMotion.close(fab, null);
    }

    if (previousFocusedElement?.isConnected) {
      previousFocusedElement.focus({ preventScroll: true });
    } else {
      fab.focus({ preventScroll: true });
    }
  }

  function closeTourWithoutUndock() {
    if (!open) return;
    open = false;
    activeTarget = null;
    layer.classList.remove('is-open');
    layer.setAttribute('aria-hidden', 'true');
    fab.setAttribute('aria-expanded', 'false');
    fab.classList.remove('is-glowing');
    document.documentElement.classList.remove('help-tour-active');
    clearTimeout(repositionTimer);
    layer.hidden = true;
  }

  function burstAtFab() {
    const rect = fab.getBoundingClientRect();
    const burst = document.createElement('div');
    burst.className = 'help-tour-finish-burst';
    burst.style.left = `${rect.left + rect.width / 2 - 5}px`;
    burst.style.top = `${rect.top + rect.height / 2 - 5}px`;
    document.body.appendChild(burst);
    setTimeout(() => burst.remove(), 720);
  }

  async function showStep(index, immediate = false) {
    if (!open || !activeSteps.length) return;
    index = Math.max(0, Math.min(index, activeSteps.length - 1));
    stepIndex = index;
    const step = activeSteps[index];
    const target = step.element;
    if (!isUsableTarget(target)) {
      const nextIndex = index + 1 < activeSteps.length ? index + 1 : index - 1;
      if (nextIndex !== index && nextIndex >= 0) return showStep(nextIndex, immediate);
      closeTour(false);
      return;
    }

    activeTarget = target;
    if (!isRectMostlyVisible(target.getBoundingClientRect())) {
      target.scrollIntoView({ behavior: immediate || window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'center', inline: 'center' });
      await sleep(immediate ? 20 : 330);
    }

    title.textContent = step.title || 'Hướng dẫn';
    text.textContent = step.text || '';
    counter.textContent = `${index + 1} / ${activeSteps.length}`;
    prevButton.disabled = index === 0;
    nextButton.textContent = index === activeSteps.length - 1 ? 'Hoàn thành ✓' : 'Tiếp →';
    renderDots();
    positionToTarget(target, immediate);

    if (!immediate) {
      card.classList.remove('is-step-changing');
      void card.offsetWidth;
      card.classList.add('is-step-changing');
      setTimeout(() => card.classList.remove('is-step-changing'), 340);
    }
  }

  function renderDots() {
    dots.innerHTML = '';
    activeSteps.forEach((_, index) => {
      const dot = document.createElement('span');
      dot.className = 'help-tour-dot';
      if (index < stepIndex) dot.classList.add('is-done');
      if (index === stepIndex) dot.classList.add('is-active');
      dots.appendChild(dot);
    });
  }

  function isRectMostlyVisible(rect) {
    const margin = 36;
    return rect.top >= margin && rect.left >= margin && rect.bottom <= window.innerHeight - margin && rect.right <= window.innerWidth - margin;
  }

  function positionToTarget(target, immediate = false) {
    if (!open || !target?.isConnected) return;
    const rect = target.getBoundingClientRect();
    const pad = 8;
    const viewportPadding = 10;

    const left = Math.max(viewportPadding, rect.left - pad);
    const top = Math.max(viewportPadding, rect.top - pad);
    const right = Math.min(window.innerWidth - viewportPadding, rect.right + pad);
    const bottom = Math.min(window.innerHeight - viewportPadding, rect.bottom + pad);

    if (immediate) spotlight.style.transition = 'none';
    else spotlight.style.transition = '';
    spotlight.style.left = `${left}px`;
    spotlight.style.top = `${top}px`;
    spotlight.style.width = `${Math.max(8, right - left)}px`;
    spotlight.style.height = `${Math.max(8, bottom - top)}px`;
    spotlight.style.setProperty('--help-radius', `${Math.min(18, Math.max(9, parseFloat(getComputedStyle(target).borderRadius) || 12))}px`);

    card.style.visibility = 'hidden';
    card.style.left = '10px';
    card.style.top = '10px';
    const cardRect = card.getBoundingClientRect();
    const gap = 16;
    const width = cardRect.width || Math.min(380, window.innerWidth - 24);
    const height = cardRect.height || 260;

    const spaces = {
      bottom: window.innerHeight - bottom,
      top,
      right: window.innerWidth - right,
      left
    };

    let side = 'bottom';
    if (spaces.bottom >= height + gap) side = 'bottom';
    else if (spaces.top >= height + gap) side = 'top';
    else if (spaces.right >= width + gap) side = 'right';
    else if (spaces.left >= width + gap) side = 'left';
    else side = spaces.bottom >= spaces.top ? 'bottom' : 'top';

    let x;
    let y;
    if (side === 'bottom' || side === 'top') {
      x = clamp(rect.left + rect.width / 2 - width / 2, viewportPadding, window.innerWidth - width - viewportPadding);
      y = side === 'bottom' ? bottom + gap : top - height - gap;
      y = clamp(y, viewportPadding, window.innerHeight - height - viewportPadding);
      const arrowX = clamp(rect.left + rect.width / 2 - x - 7, 18, width - 32);
      card.style.setProperty('--help-arrow-x', `${arrowX}px`);
    } else {
      x = side === 'right' ? right + gap : left - width - gap;
      x = clamp(x, viewportPadding, window.innerWidth - width - viewportPadding);
      y = clamp(rect.top + rect.height / 2 - height / 2, viewportPadding, window.innerHeight - height - viewportPadding);
      const arrowY = clamp(rect.top + rect.height / 2 - y - 7, 18, height - 32);
      card.style.setProperty('--help-arrow-y', `${arrowY}px`);
    }

    card.dataset.side = side;
    card.style.left = `${Math.round(x)}px`;
    card.style.top = `${Math.round(y)}px`;
    card.style.visibility = '';
    if (immediate) requestAnimationFrame(() => { spotlight.style.transition = ''; });
  }

  function clamp(value, min, max) {
    if (max < min) return min;
    return Math.min(Math.max(value, min), max);
  }

  function scheduleReposition() {
    if (!open || !activeTarget) return;
    clearTimeout(repositionTimer);
    repositionTimer = setTimeout(() => positionToTarget(activeTarget, true), 40);
  }

  fab.addEventListener('click', () => {
    if (window.FabMotion?.isAnimating?.()) return;
    if (open) void closeTour(false);
    else void start();
  });

  closeButton?.addEventListener('click', () => closeTour(false));
  skipButton?.addEventListener('click', () => closeTour(false));
  layer.querySelector('[data-help-tour-close]')?.addEventListener('click', () => closeTour(false));
  prevButton?.addEventListener('click', () => {
    if (stepIndex > 0) void showStep(stepIndex - 1);
  });
  nextButton?.addEventListener('click', () => {
    if (stepIndex >= activeSteps.length - 1) closeTour(true);
    else void showStep(stepIndex + 1);
  });

  document.addEventListener('keydown', event => {
    if (!open) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      closeTour(false);
    } else if (event.key === 'ArrowRight') {
      event.preventDefault();
      if (stepIndex >= activeSteps.length - 1) closeTour(true);
      else void showStep(stepIndex + 1);
    } else if (event.key === 'ArrowLeft') {
      event.preventDefault();
      if (stepIndex > 0) void showStep(stepIndex - 1);
    }
  }, true);

  window.addEventListener('resize', scheduleReposition);
  document.addEventListener('scroll', scheduleReposition, true);

  document.addEventListener('click', event => {
    const assistantFab = event.target.closest?.('#chatbotFab');
    const generalFab = event.target.closest?.('#generalChatFab');
    if ((assistantFab || generalFab) && open) {
      closeTourWithoutUndock();
    }
    if (!open) return;
    const nav = event.target.closest?.('.nav[data-tab]');
    if (nav) closeTour(false);
  }, true);

  function initHelpTourPen() {
    const pen = document.getElementById('helpTourPen');
    const bubble = document.getElementById('penBubble');
    const bubbleText = document.getElementById('penBubbleText');
    const penRig = document.getElementById('penRig');
    if (!pen || !bubble || !penRig) return;

    const messages = [
      'Để mình chỉ cho!',
      'Xem kỹ các bước nhé!',
      'Từng bước rất dễ hiểu!',
      'Bạn đang làm rất tốt!',
      'Bấm “Tiếp” để xem tiếp nha!',
      'Cần trợ giúp cứ bấm mình!'
    ];
    let msgIndex = 0;
    let hideTimer = 0;

    function triggerInteraction() {
      msgIndex = (msgIndex + 1) % messages.length;
      if (bubbleText) bubbleText.textContent = messages[msgIndex];

      pen.classList.add('is-active');
      clearTimeout(hideTimer);
      hideTimer = setTimeout(() => {
        pen.classList.remove('is-active');
      }, 2800);

      penRig.classList.remove('is-spinning');
      void penRig.offsetWidth;
      penRig.classList.add('is-spinning');
    }

    pen.addEventListener('click', (e) => {
      e.stopPropagation();
      triggerInteraction();
    });

    pen.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        e.stopPropagation();
        triggerInteraction();
      }
    });

    penRig.addEventListener('animationend', (e) => {
      if (e.animationName === 'help-tour-pen-spin') {
        penRig.classList.remove('is-spinning');
      }
    });
  }

  initHelpTourPen();

  window.ContextHelpTour = {
    start,
    close: closeTour,
    closeWithoutUndock: closeTourWithoutUndock,
    isOpen: () => open,
    restart: () => {
      closeTour(false);
      setTimeout(() => void start(), 260);
    }
  };
})();
