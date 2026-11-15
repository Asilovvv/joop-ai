/// Every text of the app in Russian and Kyrgyz.
///
/// The Kyrgyz texts need a check by a native speaker, as the Kyrgyz texts of Joop's own pages do.
/// The current language lives in [S.current]; LanguageCubit sets it and rebuilds the app.
class S {
  const S._({
    required this.code,
    required this.languageName,
    required this.weekdays,
    required this.months,
    required this.bookingsCount,
    required this.loadFailed,
    required this.retry,
    required this.no,
    required this.noConnection,
    required this.requestFailed,
    required this.som,
    // sign-in
    required this.tagline,
    required this.companyLogin,
    required this.staffLogin,
    required this.password,
    required this.iAmStaff,
    required this.serverAddress,
    required this.signIn,
    required this.hideServer,
    required this.otherServer,
    required this.iAmCustomer,
    required this.sameAsPanel,
    // tabs
    required this.tabToday,
    required this.tabBookings,
    required this.tabOrders,
    required this.tabLeads,
    required this.tabPrices,
    required this.signOut,
    required this.navBookings,
    required this.navOrders,
    required this.navLeads,
    required this.owner,
    // today
    required this.signedInAs,
    required this.today,
    required this.tomorrow,
    required this.next7days,
    required this.nextVisit,
    required this.noBookings7days,
    // bookings
    required this.noName,
    required this.cancelled,
    required this.confirmed,
    required this.cancelBooking,
    required this.cancelBookingQuestion,
    required this.cancelBookingText,
    required this.previousDay,
    required this.nextDay,
    required this.noBookingsThisDay,
    required this.bookingCancelled,
    required this.channelSite,
    required this.channelManual,
    // orders and requests
    required this.noOrders,
    required this.openCount,
    required this.noLeads,
    required this.newCount,
    required this.cancelOrderQuestion,
    required this.goodsBackToStock,
    required this.cancelOrder,
    required this.delivery,
    required this.deliveryTo,
    required this.pickup,
    required this.byTime,
    required this.noDescription,
    required this.done,
    required this.closedBy,
    required this.newOrder,
    required this.newOrders,
    required this.newLead,
    required this.newLeads,
    required this.customerTold,
    required this.customerNotTold,
    required this.orderMoved,
    required this.leadClosed,
    required this.leadKinds,
    required this.orderStatuses,
    required this.orderActions,
    // prices
    required this.pricesEmpty,
    required this.pricesNote,
    required this.soldOut,
    // customers
    required this.book,
    required this.customerHero,
    required this.customerHeroText,
    required this.placeCode,
    required this.placeCodeHelp,
    required this.open,
    required this.myPlaces,
    required this.removeFromList,
    required this.placeCodeInvalid,
    required this.tabChat,
    required this.tabPricesContacts,
    required this.helloBooking,
    required this.helloOther,
    required this.message,
    required this.send,
    required this.answeredBy,
    required this.staffReply,
    required this.askPricesInChat,
    required this.newBooking,
    required this.bookAction,
    required this.customerName,
    required this.customerPhoneOptional,
    required this.serviceOptional,
    required this.noFreeTimes,
    required this.chooseTime,
    required this.nameNeeded,
    required this.bookedNotice,
    required this.seatsLeft,
    required this.payment,
    required this.amountLabel,
    required this.methodCash,
    required this.methodCard,
    required this.methodTransfer,
    required this.save,
    required this.removePayment,
    required this.paymentSaved,
    required this.paymentRemoved,
    required this.cashToday,
    required this.amountNeeded,
    required this.unpaidVisits,
    required this.monthTakings,
    required this.onSale,
    required this.stopListed,
    required this.soldOutStock,
    required this.fromAltegioNote,
    required this.stopListNote,
    required this.visitsLabel,
    required this.spentLabel,
    required this.ratingLabel,
    required this.noteLabel,
    required this.tagsLabel,
    required this.noteSaved,
    required this.historyLabel,
    required this.customerOrders,
    required this.upcomingVisit,
    required this.chats,
    required this.chatsSearch,
    required this.chatsEmpty,
    required this.chatsNotFound,
    required this.youPrefix,
    required this.aiPrefix,
    required this.aiPausedChip,
    required this.blockedChip,
    required this.aiOff,
    required this.aiOn,
    required this.aiOffDone,
    required this.aiOnDone,
    required this.aiResultsTitle,
    required this.aiFigure,
    required this.moveBooking,
    required this.moveAction,
    required this.movingFrom,
    required this.movedTold,
    required this.movedCallYourself,
    required this.more,
    required this.schedule,
    required this.scheduleNote,
    required this.closeDay,
    required this.openDay,
    required this.slotClosed,
    required this.slotBusy,
    required this.noTimes,
    required this.scheduleFromAltegio,
    required this.bookingsLeftTitle,
    required this.bookingsLeftText,
    required this.gotIt,
    required this.closedTimes,
    required this.openedTimes,
    required this.answer,
    required this.answerHint,
    required this.answerSent,
    required this.aiPausedNote,
    required this.pauseWords,
    required this.aiLabel,
    required this.customerLabel,
    required this.callInstead,
  });

  final String code;
  final String languageName;
  final List<String> weekdays;
  final List<String> months;
  final String Function(int n) bookingsCount;
  final String loadFailed;
  final String retry;
  final String no;
  final String Function(String server) noConnection;
  final String requestFailed;
  final String som;
  final String tagline;
  final String companyLogin;
  final String staffLogin;
  final String password;
  final String iAmStaff;
  final String serverAddress;
  final String signIn;
  final String hideServer;
  final String otherServer;
  final String iAmCustomer;
  final String sameAsPanel;
  final String tabToday;
  final String tabBookings;
  final String tabOrders;
  final String tabLeads;
  final String tabPrices;
  final String signOut;

  /// Shorter tab names for the bottom bar, where five tabs share a narrow screen.
  final String navBookings;
  final String navOrders;
  final String navLeads;

  /// The owner's name in «Вы вошли: …» (the server sends the Russian word).
  final String owner;
  final String Function(String who) signedInAs;
  final String today;
  final String tomorrow;
  final String next7days;
  final String nextVisit;
  final String noBookings7days;
  final String noName;
  final String cancelled;
  final String confirmed;
  final String cancelBooking;
  final String cancelBookingQuestion;
  final String Function(String who) cancelBookingText;
  final String previousDay;
  final String nextDay;
  final String noBookingsThisDay;
  final String bookingCancelled;
  final String channelSite;
  final String channelManual;
  final String noOrders;
  final String Function(int n) openCount;
  final String noLeads;
  final String Function(int n) newCount;
  final String Function(int id) cancelOrderQuestion;
  final String goodsBackToStock;
  final String cancelOrder;
  final String delivery;
  final String Function(String address) deliveryTo;
  final String pickup;
  final String Function(String time) byTime;
  final String noDescription;
  final String done;
  final String Function(String who) closedBy;
  final String Function(int id) newOrder;
  final String Function(int n) newOrders;
  final String newLead;
  final String Function(int n) newLeads;
  final String customerTold;
  final String Function(String why, String phone) customerNotTold;
  final String Function(int id, String label, String told) orderMoved;
  final String leadClosed;
  final Map<String, String> leadKinds;

  /// joop/order_status.py's STATUSES; 'sent_pickup' is sent_label() for pickup.
  final Map<String, String> orderStatuses;

  /// The panel's button words (orders.html); 'sent' takes the status word.
  final Map<String, String> orderActions;

  /// The status word of an order, as joop/order_status.label() writes it.
  String orderStatus(String status, {required bool delivery}) =>
      orderStatuses[status == 'sent' && !delivery ? 'sent_pickup' : status] ?? status;

  /// The word on a step's button.
  String orderAction(String status, {required bool delivery}) =>
      status == 'sent' ? orderStatus(status, delivery: delivery) : (orderActions[status] ?? status);
  final String pricesEmpty;
  final String pricesNote;
  final String soldOut;
  final String book;
  final String customerHero;
  final String customerHeroText;
  final String placeCode;
  final String placeCodeHelp;
  final String open;
  final String myPlaces;
  final String removeFromList;
  final String placeCodeInvalid;
  final String tabChat;
  final String tabPricesContacts;
  final String helloBooking;
  final String helloOther;
  final String message;
  final String send;
  final String Function(String name) answeredBy;
  final String staffReply;
  final String askPricesInChat;
  final String newBooking;
  final String bookAction;
  final String customerName;
  final String customerPhoneOptional;
  final String serviceOptional;
  final String noFreeTimes;
  final String chooseTime;
  final String nameNeeded;
  final String Function(String name, String when) bookedNotice;
  final String Function(int n) seatsLeft;
  final String payment;
  final String amountLabel;
  final String methodCash;
  final String methodCard;
  final String methodTransfer;
  final String save;
  final String removePayment;
  final String paymentSaved;
  final String paymentRemoved;
  final String cashToday;
  final String amountNeeded;
  final String Function(int n) unpaidVisits;
  final String Function(String amount) monthTakings;
  final String onSale;
  final String stopListed;
  final String soldOutStock;
  final String fromAltegioNote;
  final String stopListNote;
  final String visitsLabel;
  final String spentLabel;
  final String ratingLabel;
  final String noteLabel;
  final String tagsLabel;
  final String noteSaved;
  final String historyLabel;
  final String customerOrders;
  final String upcomingVisit;
  final String chats;
  final String chatsSearch;
  final String chatsEmpty;
  final String chatsNotFound;
  final String youPrefix;
  final String aiPrefix;
  final String aiPausedChip;
  final String blockedChip;
  final String aiOff;
  final String aiOn;
  final String aiOffDone;
  final String aiOnDone;
  final String Function(int days) aiResultsTitle;

  /// The label of a figure from /api/mobile/ai-results; empty for a key the app does not know yet.
  final String Function(String key) aiFigure;
  final String moveBooking;
  final String moveAction;
  final String Function(String name, String when) movingFrom;
  final String Function(String when) movedTold;
  final String Function(String when) movedCallYourself;
  final String more;
  final String schedule;
  final String scheduleNote;
  final String closeDay;
  final String openDay;
  final String slotClosed;
  final String slotBusy;
  final String noTimes;
  final String scheduleFromAltegio;
  final String bookingsLeftTitle;
  final String bookingsLeftText;
  final String gotIt;
  final String Function(int n) closedTimes;
  final String Function(int n, int offered) openedTimes;
  final String answer;
  final String answerHint;
  final String answerSent;
  final String Function(String until, String pause) aiPausedNote;
  final String Function(int minutes) pauseWords;
  final String aiLabel;
  final String customerLabel;
  final String Function(String phone) callInstead;

  static S current = ru;

  static const languages = [ru, ky];

  static S byCode(String? code) => code == 'ky' ? ky : ru;

  static const ru = S._(
    code: 'ru',
    languageName: 'Русский',
    weekdays: ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс'],
    months: ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'],
    bookingsCount: _ruBookings,
    loadFailed: 'Не удалось загрузить',
    retry: 'Повторить',
    no: 'Нет',
    noConnection: _ruNoConnection,
    requestFailed: 'Ошибка запроса',
    som: 'сом',
    tagline: 'Записи, заказы и заявки из всех каналов в одном приложении',
    companyLogin: 'Логин компании или телефон',
    staffLogin: 'Ваш логин сотрудника',
    password: 'Пароль',
    iAmStaff: 'Я сотрудник',
    serverAddress: 'Адрес сервера Joop',
    signIn: 'Войти',
    hideServer: 'Скрыть адрес сервера',
    otherServer: 'Другой сервер',
    iAmCustomer: 'Я клиент: записаться',
    sameAsPanel: 'Для владельцев и сотрудников: логин и пароль те же, что в панели Joop.',
    tabToday: 'Сегодня',
    tabBookings: 'Записи',
    tabOrders: 'Заказы',
    tabLeads: 'Заявки',
    tabPrices: 'Прайс',
    signOut: 'Выйти',
    navBookings: 'Записи',
    navOrders: 'Заказы',
    navLeads: 'Заявки',
    owner: 'Владелец',
    signedInAs: _ruSignedInAs,
    today: 'сегодня',
    tomorrow: 'Завтра',
    next7days: 'За 7 дней',
    nextVisit: 'Ближайший визит',
    noBookings7days: 'На ближайшие 7 дней записей нет.',
    noName: 'Без имени',
    cancelled: 'Отменена',
    confirmed: 'Подтвердил',
    cancelBooking: 'Отменить запись',
    cancelBookingQuestion: 'Отменить запись?',
    cancelBookingText: _ruCancelBookingText,
    previousDay: 'Предыдущий день',
    nextDay: 'Следующий день',
    noBookingsThisDay: 'В этот день записей нет.',
    bookingCancelled: 'Запись отменена, время снова свободно',
    channelSite: 'Сайт',
    channelManual: 'Вручную',
    noOrders: 'Заказов пока нет. Их собирает ИИ в чатах.',
    openCount: _ruOpenCount,
    noLeads: 'Заявок нет. Сюда попадают вопросы, на которые ИИ не ответил сам.',
    newCount: _ruNewCount,
    cancelOrderQuestion: _ruCancelOrderQuestion,
    goodsBackToStock: 'Товары вернутся на склад.',
    cancelOrder: 'Отменить заказ',
    delivery: 'Доставка',
    deliveryTo: _ruDeliveryTo,
    pickup: 'Самовывоз',
    byTime: _ruByTime,
    noDescription: 'Без описания',
    done: 'Готово',
    closedBy: _ruClosedBy,
    newOrder: _ruNewOrder,
    newOrders: _ruNewOrders,
    newLead: 'Новая заявка',
    newLeads: _ruNewLeads,
    customerTold: ' Клиенту отправлено сообщение.',
    customerNotTold: _ruNotTold,
    orderMoved: _ruOrderMoved,
    leadClosed: 'Заявка закрыта',
    leadKinds: {
      'request': 'Запись без окна',
      'lead': 'Заявка',
      'media': 'Фото или файл',
      'error': 'Сбой',
      'handoff': 'Вопрос сотруднику',
    },
    orderStatuses: {
      'new': 'Новый',
      'accepted': 'Принят',
      'sent': 'В пути',
      'sent_pickup': 'Готов к выдаче',
      'done': 'Выполнен',
      'cancelled': 'Отменён',
    },
    orderActions: {'accepted': 'Принять', 'done': 'Выполнен', 'cancelled': 'Отменить'},
    pricesEmpty: 'Прайс пуст. Добавьте услуги в панели Joop.',
    pricesNote: 'Эти цены ИИ называет клиентам. Изменить их можно в панели Joop.',
    soldOut: 'Нет в наличии',
    book: 'Записаться',
    customerHero: 'Цены, свободное время и запись',
    customerHeroText: 'Отвечает ИИ-администратор компании, сразу и в любое время.',
    placeCode: 'Код компании или ссылка на её чат',
    placeCodeHelp: 'Код есть на QR-коде и в ссылке: …/c/код',
    open: 'Открыть',
    myPlaces: 'Мои компании',
    removeFromList: 'Убрать из списка',
    placeCodeInvalid: 'Введите код компании, например aktish, или ссылку на её чат.',
    tabChat: 'Чат',
    tabPricesContacts: 'Цены и контакты',
    helloBooking: 'Здравствуйте! Спросите цену или свободное время, и я запишу вас.',
    helloOther: 'Здравствуйте! Напишите ваш вопрос: цены, наличие, заказ.',
    message: 'Сообщение',
    send: 'Отправить',
    answeredBy: _ruAnsweredBy,
    staffReply: 'Администратор',
    askPricesInChat: 'Цены уточните в чате.',
    newBooking: 'Записать клиента',
    bookAction: 'Записать',
    customerName: 'Имя клиента',
    customerPhoneOptional: 'Телефон (для напоминания)',
    serviceOptional: 'Услуга (необязательно)',
    noFreeTimes: 'На этот день свободного времени нет',
    chooseTime: 'Выберите время',
    nameNeeded: 'Укажите имя клиента',
    bookedNotice: _ruBooked,
    seatsLeft: _ruSeats,
    payment: 'Оплата',
    amountLabel: 'Сумма, сом',
    methodCash: 'Наличные',
    methodCard: 'Карта',
    methodTransfer: 'Перевод',
    save: 'Сохранить',
    removePayment: 'Удалить оплату',
    paymentSaved: 'Оплата записана',
    paymentRemoved: 'Оплата удалена',
    cashToday: 'Касса сегодня',
    amountNeeded: 'Введите сумму',
    unpaidVisits: _ruUnpaid,
    monthTakings: _ruMonth,
    onSale: 'В продаже',
    stopListed: 'Стоп-лист: ИИ не предлагает',
    soldOutStock: 'Закончилось на складе',
    fromAltegioNote: 'Прайс берётся из Altegio — меняйте его там.',
    stopListNote: 'Выключите позицию — ИИ перестанет её предлагать. Цены меняются в панели Joop.',
    visitsLabel: 'Визитов',
    spentLabel: 'Всего потрачено',
    ratingLabel: 'Оценка',
    noteLabel: 'Заметка (видят сотрудники)',
    tagsLabel: 'Теги через запятую',
    noteSaved: 'Заметка сохранена',
    historyLabel: 'История визитов',
    customerOrders: 'Заказы',
    upcomingVisit: 'Следующий визит',
    chats: 'Диалоги',
    chatsSearch: 'Имя или телефон',
    chatsEmpty: 'Диалогов пока нет',
    chatsNotFound: 'Никого не нашли',
    youPrefix: 'Вы: ',
    aiPrefix: 'ИИ: ',
    aiPausedChip: 'ИИ на паузе',
    blockedChip: 'Чёрный список',
    aiOff: 'Выключить ИИ на 24 часа',
    aiOn: 'Включить ИИ',
    aiOffDone: 'ИИ молчит в этом диалоге 24 часа. Отвечайте клиенту сами.',
    aiOnDone: 'ИИ снова отвечает в этом диалоге',
    aiResultsTitle: _ruAiTitle,
    aiFigure: _ruAiFigure,
    moveBooking: 'Перенести запись',
    moveAction: 'Перенести',
    movingFrom: _ruMovingFrom,
    movedTold: _ruMovedTold,
    movedCallYourself: _ruMovedCall,
    more: 'Ещё',
    schedule: 'Окна',
    scheduleNote: 'Нажмите на время, чтобы закрыть или открыть его. Закрытое время ИИ не предлагает.',
    closeDay: 'Закрыть день',
    openDay: 'Открыть день',
    slotClosed: 'закрыто',
    slotBusy: 'занято',
    noTimes: 'На этот день времени нет',
    scheduleFromAltegio: 'Расписание из Altegio — меняйте его там.',
    bookingsLeftTitle: 'Остались записи',
    bookingsLeftText: 'Перенесите или отмените их в «Записи»: клиенты ещё не знают.',
    gotIt: 'Понятно',
    closedTimes: _ruClosedTimes,
    openedTimes: _ruOpenedTimes,
    answer: 'Ответить',
    answerHint: 'Ответ клиенту',
    answerSent: 'Ответ отправлен, заявка закрыта',
    aiPausedNote: _ruPaused,
    pauseWords: _ruPause,
    aiLabel: 'ИИ',
    customerLabel: 'Клиент',
    callInstead: _ruCallInstead,
  );

  static const ky = S._(
    code: 'ky',
    languageName: 'Кыргызча',
    weekdays: ['дш', 'шш', 'шр', 'бш', 'жм', 'иш', 'жк'],
    months: [
      'январь', 'февраль', 'март', 'апрель', 'май', 'июнь', //
      'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь',
    ],
    bookingsCount: _kyBookings,
    loadFailed: 'Жүктөлгөн жок',
    retry: 'Кайталоо',
    no: 'Жок',
    noConnection: _kyNoConnection,
    requestFailed: 'Сурамда ката кетти',
    som: 'сом',
    tagline: 'Бардык каналдардагы жазылуулар, буйрутмалар жана өтүнмөлөр бир тиркемеде',
    companyLogin: 'Логин же телефон',
    staffLogin: 'Кызматкердин логини',
    password: 'Сырсөз',
    iAmStaff: 'Мен кызматкермин',
    serverAddress: 'Joop серверинин дареги',
    signIn: 'Кирүү',
    hideServer: 'Сервердин дарегин жашыруу',
    otherServer: 'Башка сервер',
    iAmCustomer: 'Мен кардармын: жазылуу',
    sameAsPanel: 'Ээлер жана кызматкерлер үчүн: логин жана сырсөз Joop панелиндегидей эле.',
    tabToday: 'Бүгүн',
    tabBookings: 'Жазылуулар',
    tabOrders: 'Буйрутмалар',
    tabLeads: 'Өтүнмөлөр',
    tabPrices: 'Баалар',
    signOut: 'Чыгуу',
    navBookings: 'Жазылуу',
    navOrders: 'Буйрутма',
    navLeads: 'Өтүнмө',
    owner: 'Ээси',
    signedInAs: _kySignedInAs,
    today: 'бүгүн',
    tomorrow: 'Эртең',
    next7days: '7 күндө',
    nextVisit: 'Жакынкы келүү',
    noBookings7days: 'Жакынкы 7 күнгө жазылуу жок.',
    noName: 'Аты жок',
    cancelled: 'Жокко чыгарылды',
    confirmed: 'Ырастады',
    cancelBooking: 'Жазылууну жокко чыгаруу',
    cancelBookingQuestion: 'Жазылууну жокко чыгарасызбы?',
    cancelBookingText: _kyCancelBookingText,
    previousDay: 'Мурунку күн',
    nextDay: 'Кийинки күн',
    noBookingsThisDay: 'Бул күнү жазылуу жок.',
    bookingCancelled: 'Жазылуу жокко чыгарылды, убакыт кайра бош',
    channelSite: 'Сайт',
    channelManual: 'Колдон',
    noOrders: 'Азырынча буйрутма жок. Аларды ИИ чаттарда чогултат.',
    openCount: _kyOpenCount,
    noLeads: 'Өтүнмө жок. Бул жерге ИИ өзү жооп бере албаган суроолор түшөт.',
    newCount: _kyNewCount,
    cancelOrderQuestion: _kyCancelOrderQuestion,
    goodsBackToStock: 'Товарлар складка кайтат.',
    cancelOrder: 'Буйрутманы жокко чыгаруу',
    delivery: 'Жеткирүү',
    deliveryTo: _kyDeliveryTo,
    pickup: 'Өзү алып кетет',
    byTime: _kyByTime,
    noDescription: 'Сүрөттөмөсү жок',
    done: 'Даяр',
    closedBy: _kyClosedBy,
    newOrder: _kyNewOrder,
    newOrders: _kyNewOrders,
    newLead: 'Жаңы өтүнмө',
    newLeads: _kyNewLeads,
    customerTold: ' Кардарга билдирүү жөнөтүлдү.',
    customerNotTold: _kyNotTold,
    orderMoved: _kyOrderMoved,
    leadClosed: 'Өтүнмө жабылды',
    leadKinds: {
      'request': 'Бош убакытсыз жазылуу',
      'lead': 'Өтүнмө',
      'media': 'Сүрөт же файл',
      'error': 'Ката',
      'handoff': 'Кызматкерге суроо',
    },
    orderStatuses: {
      'new': 'Жаңы',
      'accepted': 'Кабыл алынды',
      'sent': 'Жолдо',
      'sent_pickup': 'Алып кетүүгө даяр',
      'done': 'Аткарылды',
      'cancelled': 'Жокко чыгарылды',
    },
    orderActions: {'accepted': 'Кабыл алуу', 'done': 'Аткарылды', 'cancelled': 'Жокко чыгаруу'},
    pricesEmpty: 'Баалар тизмеси бош. Кызматтарды Joop панелинде кошуңуз.',
    pricesNote: 'Бул бааларды ИИ кардарларга айтат. Аларды Joop панелинде өзгөртсө болот.',
    soldOut: 'Азыр жок',
    book: 'Жазылуу',
    customerHero: 'Баалар, бош убакыт жана жазылуу',
    customerHeroText: 'Компаниянын ИИ-администратору дароо жана каалаган убакта жооп берет.',
    placeCode: 'Компаниянын коду же чатынын шилтемеси',
    placeCodeHelp: 'Код QR-коддо жана шилтемеде бар: …/c/код',
    open: 'Ачуу',
    myPlaces: 'Менин компанияларым',
    removeFromList: 'Тизмеден алып салуу',
    placeCodeInvalid: 'Компаниянын кодун (мисалы, aktish) же чатынын шилтемесин жазыңыз.',
    tabChat: 'Чат',
    tabPricesContacts: 'Баалар жана байланыш',
    helloBooking: 'Саламатсызбы! Баасын же бош убакытты сураңыз, мен сизди жазып коём.',
    helloOther: 'Саламатсызбы! Сурооңузду жазыңыз: баалар, бар-жогу, буйрутма.',
    message: 'Билдирүү',
    send: 'Жөнөтүү',
    answeredBy: _kyAnsweredBy,
    staffReply: 'Администратор',
    askPricesInChat: 'Бааларды чаттан сураңыз.',
    newBooking: 'Кардарды жазуу',
    bookAction: 'Жазуу',
    customerName: 'Кардардын аты',
    customerPhoneOptional: 'Телефон (эскертүү үчүн)',
    serviceOptional: 'Кызмат (милдеттүү эмес)',
    noFreeTimes: 'Бул күнгө бош убакыт жок',
    chooseTime: 'Убакытты тандаңыз',
    nameNeeded: 'Кардардын атын жазыңыз',
    bookedNotice: _kyBooked,
    seatsLeft: _kySeats,
    payment: 'Төлөм',
    amountLabel: 'Сумма, сом',
    methodCash: 'Накталай',
    methodCard: 'Карта',
    methodTransfer: 'Которуу',
    save: 'Сактоо',
    removePayment: 'Төлөмдү өчүрүү',
    paymentSaved: 'Төлөм жазылды',
    paymentRemoved: 'Төлөм өчүрүлдү',
    cashToday: 'Бүгүнкү касса',
    amountNeeded: 'Сумманы жазыңыз',
    unpaidVisits: _kyUnpaid,
    monthTakings: _kyMonth,
    onSale: 'Сатыкта',
    stopListed: 'Стоп-тизме: ИИ сунуштабайт',
    soldOutStock: 'Кампада түгөндү',
    fromAltegioNote: "Прайс Altegio'дон алынат — ошол жерден өзгөртүңүз.",
    stopListNote: 'Позицияны өчүрсөңүз, ИИ аны сунуштабай калат. Баалар Joop панелинде өзгөрөт.',
    visitsLabel: 'Визиттер',
    spentLabel: 'Жалпы сарпталды',
    ratingLabel: 'Баа',
    noteLabel: 'Эскертме (кызматкерлер көрөт)',
    tagsLabel: 'Тегдер үтүр менен',
    noteSaved: 'Эскертме сакталды',
    historyLabel: 'Визиттердин тарыхы',
    customerOrders: 'Буйрутмалар',
    upcomingVisit: 'Кийинки визит',
    chats: 'Диалогдор',
    chatsSearch: 'Аты же телефону',
    chatsEmpty: 'Азырынча диалог жок',
    chatsNotFound: 'Эч ким табылган жок',
    youPrefix: 'Сиз: ',
    aiPrefix: 'ИИ: ',
    aiPausedChip: 'ИИ тыныгууда',
    blockedChip: 'Кара тизме',
    aiOff: 'ИИни 24 саатка өчүрүү',
    aiOn: 'ИИни күйгүзүү',
    aiOffDone: 'ИИ бул диалогдо 24 саат жооп бербейт. Кардарга өзүңүз жооп бериңиз.',
    aiOnDone: 'ИИ бул диалогдо кайра жооп берет',
    aiResultsTitle: _kyAiTitle,
    aiFigure: _kyAiFigure,
    moveBooking: 'Жазууну жылдыруу',
    moveAction: 'Жылдыруу',
    movingFrom: _kyMovingFrom,
    movedTold: _kyMovedTold,
    movedCallYourself: _kyMovedCall,
    more: 'Дагы',
    schedule: 'Убакыттар',
    scheduleNote: 'Убакытты жабуу же ачуу үчүн басыңыз. Жабык убакытты ИИ сунуштабайт.',
    closeDay: 'Күндү жабуу',
    openDay: 'Күндү ачуу',
    slotClosed: 'жабык',
    slotBusy: 'бош эмес',
    noTimes: 'Бул күнгө убакыт жок',
    scheduleFromAltegio: "Расписание Altegio'дон алынат — ошол жерден өзгөртүңүз.",
    bookingsLeftTitle: 'Жазуулар калды',
    bookingsLeftText: 'Аларды «Жазылуулар» бөлүмүндө жылдырыңыз же жокко чыгарыңыз: кардарлар азырынча билбейт.',
    gotIt: 'Түшүнүктүү',
    closedTimes: _kyClosedTimes,
    openedTimes: _kyOpenedTimes,
    answer: 'Жооп берүү',
    answerHint: 'Кардарга жооп',
    answerSent: 'Жооп жөнөтүлдү, өтүнмө жабылды',
    aiPausedNote: _kyPaused,
    pauseWords: _kyPause,
    aiLabel: 'ИИ',
    customerLabel: 'Кардар',
    callInstead: _kyCallInstead,
  );
}

String _ruBookings(int n) {
  final last2 = n % 100, last = n % 10;
  if (last2 >= 11 && last2 <= 14) return '$n записей';
  if (last == 1) return '$n запись';
  if (last >= 2 && last <= 4) return '$n записи';
  return '$n записей';
}

String _kyBookings(int n) => '$n жазылуу'; // Kyrgyz nouns do not change after a number

String _ruNoConnection(String server) => 'Нет связи с сервером ($server)';
String _kyNoConnection(String server) => 'Сервер менен байланыш жок ($server)';
String _ruSignedInAs(String who) => 'Вы вошли: $who';
String _kySignedInAs(String who) => 'Сиз кирдиңиз: $who';
String _ruCancelBookingText(String who) =>
    'Запись «$who» будет отменена, время снова станет свободным. Клиенту сообщите сами.';
String _kyCancelBookingText(String who) =>
    '«$who» жазылуусу жокко чыгарылат, убакыт кайра бош болот. Кардарга өзүңүз кабарлаңыз.';
String _ruOpenCount(int n) => 'Открытых: $n';
String _kyOpenCount(int n) => 'Ачык: $n';
String _ruNewCount(int n) => 'Новых: $n';
String _kyNewCount(int n) => 'Жаңы: $n';
String _ruCancelOrderQuestion(int id) => 'Отменить заказ №$id?';
String _kyCancelOrderQuestion(int id) => '№$id буйрутманы жокко чыгарасызбы?';
String _ruDeliveryTo(String address) => 'Доставка: $address';
String _kyDeliveryTo(String address) => 'Жеткирүү: $address';
String _ruByTime(String time) => 'Ко времени: $time';
String _kyByTime(String time) => 'Убактысы: $time';
String _ruClosedBy(String who) => 'Закрыл: $who';
String _kyClosedBy(String who) => 'Жапкан: $who';
String _ruNewOrder(int id) => 'Новый заказ №$id';
String _kyNewOrder(int id) => 'Жаңы буйрутма №$id';
String _ruNewOrders(int n) => 'Новых заказов: $n';
String _kyNewOrders(int n) => 'Жаңы буйрутмалар: $n';
String _ruNewLeads(int n) => 'Новых заявок: $n';
String _kyNewLeads(int n) => 'Жаңы өтүнмөлөр: $n';
String _ruNotTold(String why, String phone) => ' Написать клиенту не получилось: $why Телефон: $phone';
String _kyNotTold(String why, String phone) => ' Кардарга жазуу мүмкүн болгон жок: $why Телефон: $phone';
String _ruOrderMoved(int id, String label, String told) => 'Заказ №$id: $label.$told';
String _kyOrderMoved(int id, String label, String told) => '№$id буйрутма: $label.$told';
String _ruAnsweredBy(String name) => 'Отвечает ИИ-администратор $name';
String _kyAnsweredBy(String name) => '$name ИИ-администратору жооп берет';
String _ruCallInstead(String phone) => phone.isEmpty ? '' : 'Телефон клиента: $phone';
String _kyCallInstead(String phone) => phone.isEmpty ? '' : 'Кардардын телефону: $phone';
String _ruBooked(String name, String when) => 'Записали: $name, $when';
String _kyBooked(String name, String when) => '$name жазылды: $when';
String _ruSeats(int n) => 'мест: $n';
String _kySeats(int n) => 'орун: $n';
String _ruUnpaid(int n) => 'Прошли без оплаты: $n';
String _kyUnpaid(int n) => 'Төлөмсүз өткөн визиттер: $n';
String _ruMonth(String amount) => 'За месяц: $amount';
String _kyMonth(String amount) => 'Ай ичинде: $amount';
String _ruPaused(String until, String pause) =>
    'ИИ не вмешивается в этот диалог до $until. Каждый ответ сотрудника продлевает паузу на $pause.';
String _kyPaused(String until, String pause) =>
    'ИИ бул диалогго $until чейин кийлигишпейт. Кызматкердин ар бир жообу тыныгууну $pause узартат.';
String _ruPause(int m) => const {15: '15 минут', 60: '1 час', 180: '3 часа', 720: '12 часов', 1440: '24 часа'}[m] ?? '$m мин';
String _kyPause(int m) => const {15: '15 мүнөткө', 60: '1 саатка', 180: '3 саатка', 720: '12 саатка', 1440: '24 саатка'}[m] ?? '$m мүнөткө';
String _ruAiTitle(int days) => 'ИИ за $days дней';
String _kyAiTitle(int days) => 'ИИ $days күндө';
String _ruAiFigure(String key) => const {
      'conversations': 'диалогов с клиентами',
      'off_hours_conversations': 'из них в нерабочее время',
      'bookings': 'записей сделал ИИ',
      'off_hours_bookings': 'записей в нерабочее время',
      'orders': 'заказов принял ИИ',
      'stays': 'броней сделал ИИ',
      'requests': 'заявок на запись (перезвонить)',
      'qualified': 'заявок собрал ИИ',
      'handed_to_people': 'вопросов передано людям',
    }[key] ??
    '';
String _kyAiFigure(String key) => const {
      'conversations': 'кардарлар менен диалог',
      'off_hours_conversations': 'анын ичинде жумуштан тышкары',
      'bookings': 'ИИ жазган визит',
      'off_hours_bookings': 'жумуштан тышкаркы жазуу',
      'orders': 'ИИ кабыл алган буйрутма',
      'stays': 'ИИ жасаган бронь',
      'requests': 'жазылууга өтүнмө (кайра чалуу)',
      'qualified': 'ИИ чогулткан өтүнмө',
      'handed_to_people': 'адамдарга берилген суроо',
    }[key] ??
    '';
String _ruMovingFrom(String name, String when) => 'Сейчас: $name, $when';
String _kyMovingFrom(String name, String when) => 'Азыр: $name, $when';
String _ruMovedTold(String when) => 'Перенесли на $when. Клиенту написали в чат.';
String _kyMovedTold(String when) => '$when убакытка жылдырылды. Кардарга чатка жазылды.';
String _ruMovedCall(String when) => 'Перенесли на $when. Сообщите клиенту сами: написать ему из Joop нельзя.';
String _kyMovedCall(String when) => '$when убакытка жылдырылды. Кардарга өзүңүз билдириңиз: Joopтон жазуу мүмкүн эмес.';
String _ruClosedTimes(int n) => 'Закрыто времени: $n. ИИ не будет на него записывать.';
String _kyClosedTimes(int n) => 'Жабылды: $n. ИИ ага жазбайт.';
String _ruOpenedTimes(int n, int offered) =>
    'Открыто времени: $n.${offered > 0 ? ' Предложено клиентам из листа ожидания: $offered.' : ''}';
String _kyOpenedTimes(int n, int offered) =>
    'Ачылды: $n.${offered > 0 ? ' Күтүү тизмесиндеги кардарларга сунушталды: $offered.' : ''}';
