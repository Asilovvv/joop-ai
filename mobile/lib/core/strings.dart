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
    required this.addService,
    required this.exampleBanner,
    required this.deleteExample,
    required this.deleteExampleConfirm,
    required this.cancel,
    required this.serviceName,
    required this.servicePrice,
    required this.servicePriceHint,
    required this.serviceNameKy,
    required this.serviceNote,
    required this.deleteService,
    required this.serviceNameEmpty,
    required this.pricesInApp,
    required this.contactsTitle,
    required this.address,
    required this.phone,
    required this.hoursText,
    required this.hoursTextHint,
    required this.workStart,
    required this.workEnd,
    required this.daysOffLabel,
    required this.fromExample,
    required this.saved,
    required this.fillHere,
    required this.timeFormat,
    required this.peopleExampleBanner,
    required this.peopleExampleConfirm,
    required this.personName,
    required this.personRole,
    required this.personHandles,
    required this.personCapacity,
    required this.personGroup,
    required this.personDelete,
    required this.personDeleteNote,
    required this.peopleEmpty,
    required this.newPerson,
    required this.peopleExampleDeleted,
    required this.exampleChip,
    required this.personSeats,
    required this.personGroupUpTo,
    required this.openWindows,
    required this.windowsTitle,
    required this.windowsHint,
    required this.windowsDays,
    required this.windowsStep,
    required this.windowsNone,
    required this.windowsOpened,
    required this.freeAhead,
    required this.newService,
    required this.editService,
    required this.stopListEditNote,
    required this.exampleDeleted,
    required this.no,
    required this.noConnection,
    required this.httpsOnly,
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
    required this.setupTitle,
    required this.botToken,
    required this.connectBot,
    required this.botHowTo,
    required this.pageBookingSwitch,
    required this.pageBookingHint,
    required this.pageBookingUnpaid,
    required this.inPanel,
    required this.copy,
    required this.qrHint,
    required this.goToPay,
    required this.tellOwner,
    required this.payLinkCopied,
    required this.onlineHint,
    required this.onlineTablesHint,
    required this.tryTitle,
    required this.newDialogue,
    required this.tryHint,
    required this.tryInputHint,
    required this.openTry,
    required this.testBookingsCancelled,
    required this.setupProgress,
    required this.trialNote,
    required this.signUpNext,
    required this.signUp,
    required this.signUpTitle,
    required this.businessName,
    required this.niche,
    required this.yourName,
    required this.businessPhone,
    required this.newPassword,
    required this.createCompany,
    required this.signUpDone,
    required this.continueToApp,
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
    required this.channelApi,
    required this.channelPage,
    required this.remindByHand,
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
    // stays: hotel rooms, cars, banquet halls
    required this.stayTitle,
    required this.navStays,
    required this.noStays,
    required this.newStays,
    required this.staysCount,
    required this.stayNights,
    required this.stayGuests,
    required this.cancelStay,
    required this.cancelStayQuestion,
    required this.stayCancelled,
    required this.stayCancelledTag,
    required this.newStay,
    required this.stayCheckIn,
    required this.stayDate,
    required this.stayDays,
    required this.chooseRoom,
    required this.roomFree,
    required this.noRoomsFree,
    required this.stayBooked,
    required this.manualTag,
    required this.guestsLabel,
    required this.testTag,
    required this.free,
    required this.exampleRow,
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
    required this.depositReceived,
    required this.depositsToCheck,
    required this.depositOverdue,
    required this.depositToldCustomer,
    required this.depositTellYourself,
    required this.depositAwaiting,
    required this.depositCheck,
    required this.depositPaid,
    required this.customersTitle,
    required this.customersEmpty,
    required this.menu,
    required this.allTags,
    required this.customerLine,
    required this.shownOf,
    required this.answer,
    required this.answerHint,
    required this.answerSent,
    required this.aiPausedNote,
    required this.pauseWords,
    required this.aiLabel,
    required this.customerLabel,
    required this.callInstead,
    required this.tabJobs,
    required this.navJobs,
    required this.jobsHint,
    required this.newJob,
    required this.jobNumber,
    required this.jobPhone,
    required this.jobCustomer,
    required this.jobPrice,
    required this.jobNote,
    required this.jobReadyBy,
    required this.jobPickDate,
    required this.jobFill,
    required this.jobsSearch,
    required this.jobsEmpty,
    required this.jobsExampleBanner,
    required this.jobsExampleConfirm,
    required this.jobTold,
    required this.jobsDone,
    required this.jobsExampleDeleted,
    required this.jobStatus,
    required this.jobDue,
    required this.jobAccepted,
    required this.jobReadyTold,
    required this.jobReadyCall,
    required this.jobSaved,
  });

  final String code;
  final String languageName;
  final List<String> weekdays;
  final List<String> months;
  final String Function(int n) bookingsCount;
  final String loadFailed;
  final String retry;
  final String addService;
  final String exampleBanner;
  final String deleteExample;
  final String deleteExampleConfirm;
  final String cancel;
  final String serviceName;
  final String servicePrice;
  final String servicePriceHint;
  final String serviceNameKy;
  final String serviceNote;
  final String deleteService;
  final String serviceNameEmpty;
  final String pricesInApp;
  final String contactsTitle;
  final String address;
  final String phone;
  final String hoursText;
  final String hoursTextHint;
  final String workStart;
  final String workEnd;
  final String daysOffLabel;
  final String fromExample;
  final String saved;
  final String fillHere;
  final String timeFormat;
  final String peopleExampleBanner;
  final String peopleExampleConfirm;
  final String personName;
  final String personRole;
  final String personHandles;
  final String personCapacity;
  final String personGroup;
  final String personDelete;
  final String personDeleteNote;
  final String peopleEmpty;
  final String newPerson;
  final String Function(int n) peopleExampleDeleted;
  final String exampleChip;
  final String Function(int n) personSeats;
  final String Function(int n) personGroupUpTo;
  final String openWindows;
  final String windowsTitle;
  final String windowsHint;
  final String windowsDays;
  final String windowsStep;
  final String windowsNone;
  final String Function(int n) windowsOpened;
  final String Function(int n) freeAhead;
  final String newService;
  final String editService;
  final String stopListEditNote;
  final String Function(int n) exampleDeleted;
  final String no;
  final String Function(String server) noConnection;
  final String Function(String server) httpsOnly;
  final String requestFailed;
  final String som;
  final String tagline;
  final String companyLogin;
  final String staffLogin;
  final String password;
  final String iAmStaff;
  final String serverAddress;
  final String signIn;
  final String setupTitle;
  final String botToken;
  final String connectBot;
  final String botHowTo;
  final String pageBookingSwitch;
  final String pageBookingHint;
  final String pageBookingUnpaid;
  final String inPanel;
  final String copy;
  final String qrHint;
  final String goToPay;
  final String tellOwner;
  final String payLinkCopied;
  final String onlineHint;
  final String onlineTablesHint;
  final String tryTitle;
  final String newDialogue;
  final String tryHint;
  final String tryInputHint;
  final String openTry;
  final String Function(int n) testBookingsCancelled;
  final String Function(int done, int total) setupProgress;
  final String signUp;
  final String signUpTitle;
  final String businessName;
  final String niche;
  final String yourName;
  final String businessPhone;
  final String newPassword;
  final String createCompany;
  final String signUpDone;
  final String continueToApp;
  final String Function(int days) trialNote;
  final String Function(String login, String setup) signUpNext;
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

  /// A booking from a partner's system or another assistant (the panel's «через API»).
  final String channelApi;

  /// A booking the customer made on the booking page, without a chat (the panel's «со страницы записи»).
  final String channelPage;

  /// A booking with no chat for the reminder: staff call the day before.
  final String remindByHand;
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

  /// The tab's title by what is booked: room | car | hall (the panel's «Брони номеров/машин/залов»).
  final String Function(String kind) stayTitle;
  final String navStays;
  final String Function(String kind) noStays;
  final String Function(int n) newStays;
  final String Function(int n) staysCount;
  final String Function(int n) stayNights;
  final String Function(int n) stayGuests;
  final String cancelStay;
  final String Function(String who) cancelStayQuestion;

  /// After a cancel: what is free again, and that staff tell the customer (the panel says the same).
  final String Function(String kind) stayCancelled;
  final String stayCancelledTag;

  /// «Забронировать»: a guest who phoned or walked in.
  final String newStay;
  final String stayCheckIn;
  final String stayDate;
  final String Function(int n) stayDays;
  final String Function(String kind) chooseRoom;
  final String Function(int n) roomFree;
  final String noRoomsFree;
  final String Function(String who, String dates) stayBooked;
  final String manualTag;
  final String guestsLabel;
  final String testTag;

  /// A price of 0: «бесплатно», not «0 сом».
  final String free;

  /// A price row still the sign-up example's: not named to real customers until changed in the panel.
  final String exampleRow;
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
  final String Function(String key, int n) aiFigure; // the words under a number: «4 диалога с клиентами»
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
  final String depositReceived;
  final String depositsToCheck;
  final String depositOverdue;
  final String depositToldCustomer;
  final String depositTellYourself;
  final String Function(String amount, String until) depositAwaiting;
  final String Function(String amount) depositCheck;
  final String Function(String amount) depositPaid;
  final String customersTitle;
  final String customersEmpty;
  final String menu;
  final String allTags;
  final String Function(int visits, String spent) customerLine;
  final String Function(int shown, int total) shownOf;
  final String answer;
  final String answerHint;
  final String answerSent;
  final String Function(String until, String pause) aiPausedNote;
  final String Function(int minutes) pauseWords;
  final String aiLabel;
  final String customerLabel;
  final String Function(String phone) callInstead;

  // «Заказы в работе»: receipts at the counter (a repair shop, an optician, a car service, a furniture maker)
  final String tabJobs;
  final String navJobs;
  final String jobsHint;
  final String newJob;
  final String jobNumber;
  final String jobPhone;
  final String jobCustomer;
  final String jobPrice;
  final String jobNote;
  final String jobReadyBy;
  final String jobPickDate;
  final String jobFill;
  final String jobsSearch;
  final String jobsEmpty;
  final String jobsExampleBanner;
  final String jobsExampleConfirm;
  final String jobTold;
  final String Function(bool delivered) jobsDone;
  final String Function(int n) jobsExampleDeleted;
  final String Function(String status, bool delivered) jobStatus;
  final String Function(String day) jobDue;
  final String Function(String number) jobAccepted;
  final String Function(String number) jobReadyTold;
  final String Function(String number, String phone) jobReadyCall;
  final String Function(String number, String status) jobSaved;

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
    addService: 'Добавить',
    exampleBanner: 'Это пример прайса: ИИ не называет его клиентам. Замените названия и цены на свои — нажмите на позицию — или удалите пример целиком и добавьте свои.',
    deleteExample: 'Удалить пример',
    deleteExampleConfirm: 'Удалить все позиции примера? Ваши собственные позиции останутся.',
    cancel: 'Отмена',
    serviceName: 'Название',
    servicePrice: 'Цена, сом',
    servicePriceHint: 'Число — ИИ назовёт его как есть. Можно и «от 900».',
    serviceNameKy: 'Название по-кыргызски (по желанию)',
    serviceNote: 'Что добавить клиенту (длительность, что входит)',
    deleteService: 'Удалить позицию',
    serviceNameEmpty: 'Напишите название.',
    pricesInApp: 'Это можно сделать прямо в приложении: вкладка «Прайс».',
    contactsTitle: 'Контакты и часы',
    address: 'Адрес',
    phone: 'Телефон для клиентов',
    hoursText: 'Часы работы, как сказать клиенту',
    hoursTextHint: 'Например: Пн–Сб 10:00–20:00, вс выходной',
    workStart: 'Начало записи',
    workEnd: 'Конец',
    daysOffLabel: 'Выходные дни',
    fromExample: 'из примера — клиентам не говорится, впишите своё',
    saved: 'Сохранено.',
    fillHere: 'Заполнить здесь',
    timeFormat: 'Время в виде 09:00',
    peopleExampleBanner: 'Это пример из вашей сферы: клиентов к ним не записывают. Нажмите на строку, чтобы вписать своего, или удалите пример целиком.',
    peopleExampleConfirm: 'Удалить всех из примера вместе с их свободными окнами? Ваши люди и записи останутся.',
    personName: 'Имя или название',
    personRole: 'Должность (по желанию)',
    personHandles: 'Чем занимается — по этому ИИ выбирает, к кому записать',
    personCapacity: 'Мест (гостей за столом, в зале)',
    personGroup: 'Мест в группе (0 — индивидуально)',
    personDelete: 'Убрать',
    personDeleteNote: 'Записи к нему останутся, свободные окна удалятся.',
    peopleEmpty: 'Пока никого нет — добавьте кнопкой «Добавить».',
    newPerson: 'Добавить',
    peopleExampleDeleted: _ruPeopleExampleDeleted,
    exampleChip: 'пример',
    personSeats: _ruPersonSeats,
    personGroupUpTo: _ruPersonGroupUpTo,
    openWindows: 'Открыть окна',
    windowsTitle: 'Свободные окна для записи',
    windowsHint: 'С завтрашнего дня, выходные пропускаются, уже открытое время не дублируется.',
    windowsDays: 'На сколько дней',
    windowsStep: 'Одна запись, минут',
    windowsNone: 'Новых окон нет: это время уже открыто.',
    windowsOpened: _ruWindowsOpened,
    freeAhead: _ruFreeAhead,
    newService: 'Новая позиция',
    editService: 'Позиция прайса',
    stopListEditNote: 'Нажмите на позицию, чтобы изменить название и цену. Выключите — ИИ перестанет её предлагать.',
    exampleDeleted: _ruExampleDeleted,
    no: 'Нет',
    noConnection: _ruNoConnection,
    httpsOnly: _ruHttpsOnly,
    requestFailed: 'Ошибка запроса',
    som: 'сом',
    tagline: 'Записи, заказы и заявки из всех каналов в одном приложении',
    companyLogin: 'Логин компании или телефон',
    staffLogin: 'Ваш логин сотрудника',
    password: 'Пароль',
    iAmStaff: 'Я сотрудник',
    serverAddress: 'Адрес сервера Joop',
    signIn: 'Войти',
    setupTitle: 'Запуск',
    botToken: 'Токен бота от @BotFather',
    connectBot: 'Подключить бота',
    botHowTo: 'В Telegram: @BotFather → /newbot → скопируйте токен и вставьте сюда.',
    pageBookingSwitch: 'Клиенты записываются сами',
    pageBookingHint: 'Клиент выбирает время на странице, без переписки. Ссылку поставьте в шапку Instagram и в 2ГИС:',
    pageBookingUnpaid: 'Сейчас не принимает записи: нужна подписка или пробный период.',
    inPanel: 'В панели:',
    copy: 'Копировать',
    qrHint: 'QR-код этой страницы: покажите клиенту с экрана (нажмите, чтобы увеличить) или распечатайте на стойку.',
    goToPay: 'Перейти к оплате',
    tellOwner: 'Оплачивает владелец — скажите ему.',
    payLinkCopied: 'Ссылка на оплату скопирована — откройте её в браузере.',
    onlineHint: 'Страница с ценами, адресом и кнопками в ваши чаты. Ссылку — в шапку Instagram и в 2ГИС:',
    onlineTablesHint: 'Гости открывают меню по QR-коду и заказывают в чат. QR-коды для каждого стола (с номером) печатаются в панели: «QR-меню» → «Печать QR-кодов».',
    tryTitle: 'Тестовый чат',
    newDialogue: 'Новый диалог',
    tryHint: 'Напишите как клиент: по-русски и по-кыргызски, спросите цену, попробуйте записаться. Эти сообщения нигде не считаются.',
    tryInputHint: 'Сообщение как от клиента',
    openTry: 'Открыть тестовый чат',
    testBookingsCancelled: _ruTestBookingsCancelled,
    setupProgress: _ruSetupProgress,
    signUp: 'Зарегистрировать компанию',
    signUpTitle: 'Новая компания',
    businessName: 'Название компании',
    niche: 'Чем занимаетесь',
    yourName: 'Ваше имя',
    businessPhone: 'Телефон',
    newPassword: 'Пароль, от 8 символов',
    createCompany: 'Создать',
    signUpDone: 'Компания создана',
    continueToApp: 'Перейти в приложение',
    trialNote: _ruTrial,
    signUpNext: _ruSignUpNext,
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
    channelApi: 'через API',
    channelPage: 'со страницы записи',
    remindByHand: 'напомнить вручную',
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
    stayTitle: _ruStayTitle,
    navStays: 'Брони',
    noStays: _ruNoStays,
    newStays: _ruNewStays,
    staysCount: _ruStaysCount,
    stayNights: _ruNights,
    stayGuests: _ruGuests,
    cancelStay: 'Отменить бронь',
    cancelStayQuestion: _ruCancelStayQuestion,
    stayCancelled: _ruStayCancelled,
    stayCancelledTag: 'отменена',
    newStay: 'Забронировать',
    stayCheckIn: 'Заезд',
    stayDate: 'Дата',
    stayDays: _ruDays,
    chooseRoom: _ruChooseRoom,
    roomFree: _ruRoomFree,
    noRoomsFree: 'На эти даты свободных нет.',
    stayBooked: _ruStayBooked,
    manualTag: 'вручную',
    guestsLabel: 'Гостей',
    testTag: 'тест',
    free: 'бесплатно',
    exampleRow: 'из примера — клиентам не называется',
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
    scheduleNote: 'Нажмите на время, чтобы закрыть или открыть его. Закрытое время клиентам не предлагается — ни в чате, ни на странице записи.',
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
    depositReceived: 'Предоплата получена',
    depositsToCheck: 'Проверьте предоплату',
    depositOverdue: 'предоплата не пришла',
    depositToldCustomer: 'Предоплата отмечена. Клиенту отправлено подтверждение.',
    depositTellYourself: 'Предоплата отмечена. Подтвердите клиенту сами: написать ему из Joop сейчас нельзя.',
    depositAwaiting: _ruDepAwait,
    depositCheck: _ruDepCheck,
    depositPaid: _ruDepPaid,
    customersTitle: 'Клиенты',
    customersEmpty: 'Клиентов пока нет',
    menu: 'Меню',
    allTags: 'Все',
    customerLine: _ruCustomerLine,
    shownOf: _ruShownOf,
    answer: 'Ответить',
    answerHint: 'Ответ клиенту',
    answerSent: 'Ответ отправлен, заявка закрыта',
    aiPausedNote: _ruPaused,
    pauseWords: _ruPause,
    aiLabel: 'ИИ',
    customerLabel: 'Клиент',
    callInstead: _ruCallInstead,
    tabJobs: 'Заказы в работе',
    navJobs: 'В работе',
    jobsHint: 'Клиент спрашивает в чате, готов ли заказ, — ИИ отвечает по статусу. Ставите «готов» — клиенту сразу приходит сообщение.',
    newJob: 'Принять заказ',
    jobNumber: 'Номер квитанции',
    jobPhone: 'Телефон клиента',
    jobCustomer: 'Имя клиента',
    jobPrice: 'Стоимость',
    jobNote: 'Заметка для клиента',
    jobReadyBy: 'Срок готовности',
    jobPickDate: 'Выбрать дату',
    jobFill: 'Заполните: по этому ИИ найдёт заказ',
    jobsSearch: 'Номер, телефон или имя',
    jobsEmpty: 'Нет заказов в работе.',
    jobsExampleBanner: 'Квитанции из примера: в тестовом чате ИИ их знает, настоящим клиентам — нет. Удалите их, когда начнёте принимать свои заказы.',
    jobsExampleConfirm: 'Удалить квитанции из примера?',
    jobTold: 'клиенту написали',
    jobsDone: _ruJobsDone,
    jobsExampleDeleted: _ruJobsExampleDeleted,
    jobStatus: _ruJobStatus,
    jobDue: _ruJobDue,
    jobAccepted: _ruJobAccepted,
    jobReadyTold: _ruJobReadyTold,
    jobReadyCall: _ruJobReadyCall,
    jobSaved: _ruJobSaved,
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
    addService: 'Кошуу', // check with a native speaker
    exampleBanner: 'Бул баалардын мисалы: ИИ аны кардарларга айтпайт. Аталыштарын жана бааларын өзүңүздүкүнө алмаштырыңыз — позицияны басыңыз — же мисалды толук өчүрүп, өзүңүздүкүн кошуңуз.', // check with a native speaker
    deleteExample: 'Мисалды өчүрүү', // check with a native speaker
    deleteExampleConfirm: 'Мисалдын бардык позицияларын өчүрөсүзбү? Өзүңүздүн позицияларыңыз калат.', // check with a native speaker
    cancel: 'Жокко чыгаруу', // check with a native speaker
    serviceName: 'Аталышы', // check with a native speaker
    servicePrice: 'Баасы, сом', // check with a native speaker
    servicePriceHint: 'Сан — ИИ аны ошол бойдон айтат. «900дөн» деп да жазса болот.', // check with a native speaker
    serviceNameKy: 'Кыргызча аталышы (каалоо боюнча)', // check with a native speaker
    serviceNote: 'Кардарга эмне кошуп айтуу керек (узактыгы, эмне кирет)', // check with a native speaker
    deleteService: 'Позицияны өчүрүү', // check with a native speaker
    serviceNameEmpty: 'Аталышын жазыңыз.', // check with a native speaker
    pricesInApp: 'Муну тиркемеде эле жасаса болот: «Прайс» өтмөгү.', // check with a native speaker
    contactsTitle: 'Байланыш жана саат', // check with a native speaker
    address: 'Дарек', // check with a native speaker
    phone: 'Кардарлар үчүн телефон', // check with a native speaker
    hoursText: 'Иштөө убактысы, кардарга кантип айтуу', // check with a native speaker
    hoursTextHint: 'Мисалы: Дш–Иш 10:00–20:00, жк дем алыш', // check with a native speaker
    workStart: 'Жазылуунун башталышы', // check with a native speaker
    workEnd: 'Аягы', // check with a native speaker
    daysOffLabel: 'Дем алыш күндөр', // check with a native speaker
    fromExample: 'мисалдан — кардарларга айтылбайт, өзүңүздүкүн жазыңыз', // check with a native speaker
    saved: 'Сакталды.', // check with a native speaker
    fillHere: 'Ушул жерден толтуруу', // check with a native speaker
    timeFormat: 'Убакыт 09:00 түрүндө', // check with a native speaker
    peopleExampleBanner: 'Бул сиздин тармактан мисал: кардарлар аларга жазылбайт. Өзүңүздүкүн жазуу үчүн сапты басыңыз же мисалды толук өчүрүңүз.', // check with a native speaker
    peopleExampleConfirm: 'Мисалдагылардын баарын бош убактылары менен кошо өчүрөсүзбү? Өзүңүздүн адамдарыңыз жана жазылуулар калат.', // check with a native speaker
    personName: 'Аты же аталышы', // check with a native speaker
    personRole: 'Кызматы (каалоо боюнча)', // check with a native speaker
    personHandles: 'Эмне менен алектенет — ИИ ушуга карап кимге жазууну тандайт', // check with a native speaker
    personCapacity: 'Орун (столдо, залда канча конок)', // check with a native speaker
    personGroup: 'Топтогу орун (0 — жекече)', // check with a native speaker
    personDelete: 'Алып салуу', // check with a native speaker
    personDeleteNote: 'Ага жазылуулар калат, бош убактылар өчөт.', // check with a native speaker
    peopleEmpty: 'Азырынча эч ким жок — «Кошуу» баскычы менен кошуңуз.', // check with a native speaker
    newPerson: 'Кошуу', // check with a native speaker
    peopleExampleDeleted: _kyPeopleExampleDeleted,
    exampleChip: 'мисал', // check with a native speaker
    personSeats: _kyPersonSeats,
    personGroupUpTo: _kyPersonGroupUpTo,
    openWindows: 'Убакыт ачуу', // check with a native speaker
    windowsTitle: 'Жазылуу үчүн бош убакыт', // check with a native speaker
    windowsHint: 'Эртеңден баштап, дем алыш күндөр өткөрүлөт, ачык убакыт кайталанбайт.', // check with a native speaker
    windowsDays: 'Канча күнгө', // check with a native speaker
    windowsStep: 'Бир жазылуу, мүнөт', // check with a native speaker
    windowsNone: 'Жаңы убакыт жок: бул убакыт буга чейин ачык.', // check with a native speaker
    windowsOpened: _kyWindowsOpened,
    freeAhead: _kyFreeAhead,
    newService: 'Жаңы позиция', // check with a native speaker
    editService: 'Прайстын позициясы', // check with a native speaker
    stopListEditNote: 'Атын жана баасын өзгөртүү үчүн позицияны басыңыз. Өчүрсөңүз, ИИ аны сунуштабай калат.', // check with a native speaker
    exampleDeleted: _kyExampleDeleted,
    no: 'Жок',
    noConnection: _kyNoConnection,
    httpsOnly: _kyHttpsOnly,
    requestFailed: 'Сурамда ката кетти',
    som: 'сом',
    tagline: 'Бардык каналдардагы жазылуулар, буйрутмалар жана өтүнмөлөр бир тиркемеде',
    companyLogin: 'Логин же телефон',
    staffLogin: 'Кызматкердин логини',
    password: 'Сырсөз',
    iAmStaff: 'Мен кызматкермин',
    serverAddress: 'Joop серверинин дареги',
    signIn: 'Кирүү',
    setupTitle: 'Ишке киргизүү', // check with a native speaker
    botToken: '@BotFather берген бот токени', // check with a native speaker
    connectBot: 'Ботту туташтыруу', // check with a native speaker
    botHowTo: "Telegram'да: @BotFather → /newbot → токенди көчүрүп, бул жерге коюңуз.", // check with a native speaker
    pageBookingSwitch: 'Кардарлар өздөрү жазылышат', // check with a native speaker
    pageBookingHint: "Кардар убакытты баракта тандайт, жазышпай эле. Шилтемени Instagram'дын башына жана 2ГИСке коюңуз:", // check with a native speaker
    pageBookingUnpaid: 'Азыр жазылуу кабыл алынбайт: жазылуу же сыноо мөөнөтү керек.', // check with a native speaker
    inPanel: 'Панелде:', // check with a native speaker
    copy: 'Көчүрүү', // check with a native speaker
    qrHint: 'Бул барактын QR-коду: кардарга экрандан көрсөтүңүз (чоңойтуу үчүн басыңыз) же басып чыгарып, стойкага коюңуз.', // check with a native speaker
    goToPay: 'Төлөмгө өтүү', // check with a native speaker
    tellOwner: 'Ээси төлөйт — ага айтып коюңуз.', // check with a native speaker
    payLinkCopied: 'Төлөм шилтемеси көчүрүлдү — аны браузерде ачыңыз.', // check with a native speaker
    onlineHint: "Бааларыңыз, дарегиңиз жана чаттарыңызга баскычтар бар барак. Шилтемени Instagram'дын башына жана 2ГИСке коюңуз:", // check with a native speaker
    onlineTablesHint: "Коноктор менюну QR-код аркылуу ачып, чатка буйрутма беришет. Ар бир үстөлдүн QR-коддору (номери менен) панелде басылат: «QR-меню» → «QR-коддорду басуу».", // check with a native speaker
    tryTitle: 'Сынак чат', // check with a native speaker
    newDialogue: 'Жаңы диалог', // check with a native speaker
    tryHint: 'Кардар катары жазыңыз: орусча жана кыргызча, баасын сураңыз, жазылып көрүңүз. Бул билдирүүлөр эч жерде эсептелбейт.', // check with a native speaker
    tryInputHint: 'Кардардын атынан билдирүү', // check with a native speaker
    openTry: 'Сынак чатты ачуу', // check with a native speaker
    testBookingsCancelled: _kyTestBookingsCancelled,
    setupProgress: _kySetupProgress,
    signUp: 'Компанияны каттоо', // check with a native speaker
    signUpTitle: 'Жаңы компания', // check with a native speaker
    businessName: 'Компаниянын аталышы', // check with a native speaker
    niche: 'Эмне менен алектенесиз', // check with a native speaker
    yourName: 'Атыңыз', // check with a native speaker
    businessPhone: 'Телефон', // check with a native speaker
    newPassword: 'Сырсөз, 8 белгиден кем эмес', // check with a native speaker
    createCompany: 'Түзүү', // check with a native speaker
    signUpDone: 'Компания түзүлдү', // check with a native speaker
    continueToApp: 'Тиркемеге өтүү', // check with a native speaker
    trialNote: _kyTrial,
    signUpNext: _kySignUpNext,
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
    channelApi: 'API аркылуу', // check with a native speaker
    channelPage: 'жазылуу барагынан', // check with a native speaker
    remindByHand: 'кол менен эскертүү', // check with a native speaker
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
    stayTitle: _kyStayTitle,
    navStays: 'Брондор',
    noStays: _kyNoStays,
    newStays: _kyNewStays,
    staysCount: _kyStaysCount,
    stayNights: _kyNights,
    stayGuests: _kyGuests,
    cancelStay: 'Брондоону жокко чыгаруу',
    cancelStayQuestion: _kyCancelStayQuestion,
    stayCancelled: _kyStayCancelled,
    stayCancelledTag: 'жокко чыгарылды',
    newStay: 'Брондоо',
    stayCheckIn: 'Келүү',
    stayDate: 'Күнү',
    stayDays: _kyDays,
    chooseRoom: _kyChooseRoom,
    roomFree: _kyRoomFree,
    noRoomsFree: 'Бул күндөргө бош жок.',
    stayBooked: _kyStayBooked,
    manualTag: 'кол менен',
    guestsLabel: 'Конок саны',
    testTag: 'тест',
    free: 'акысыз',
    exampleRow: 'мисалдан — кардарларга айтылбайт',
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
    scheduleNote: 'Убакытты жабуу же ачуу үчүн басыңыз. Жабык убакыт кардарларга сунушталбайт — чатта да, жазылуу барагында да.' /* check with a native speaker */,
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
    depositReceived: 'Алдын ала төлөм алынды',
    depositsToCheck: 'Алдын ала төлөмдү текшериңиз',
    depositOverdue: 'алдын ала төлөм келген жок',
    depositToldCustomer: 'Алдын ала төлөм белгиленди. Кардарга ырастоо жөнөтүлдү.',
    depositTellYourself: 'Алдын ала төлөм белгиленди. Кардарга өзүңүз билдириңиз: Joopтон азыр жазуу мүмкүн эмес.',
    depositAwaiting: _kyDepAwait,
    depositCheck: _kyDepCheck,
    depositPaid: _kyDepPaid,
    customersTitle: 'Кардарлар',
    customersEmpty: 'Азырынча кардар жок',
    menu: 'Меню',
    allTags: 'Баары',
    customerLine: _kyCustomerLine,
    shownOf: _kyShownOf,
    answer: 'Жооп берүү',
    answerHint: 'Кардарга жооп',
    answerSent: 'Жооп жөнөтүлдү, өтүнмө жабылды',
    aiPausedNote: _kyPaused,
    pauseWords: _kyPause,
    aiLabel: 'ИИ',
    customerLabel: 'Кардар',
    callInstead: _kyCallInstead,
    tabJobs: 'Иштеги буйрутмалар', // check with a native speaker
    navJobs: 'Иште', // check with a native speaker
    jobsHint: 'Кардар чатта буйрутмасы даярбы деп сураса, ИИ статус боюнча жооп берет. «Даяр» деп белгилесеңиз, кардарга дароо билдирүү барат.', // check with a native speaker
    newJob: 'Буйрутма кабыл алуу', // check with a native speaker
    jobNumber: 'Квитанциянын номери', // check with a native speaker
    jobPhone: 'Кардардын телефону', // check with a native speaker
    jobCustomer: 'Кардардын аты', // check with a native speaker
    jobPrice: 'Баасы', // check with a native speaker
    jobNote: 'Кардар үчүн эскертме', // check with a native speaker
    jobReadyBy: 'Даяр болуу мөөнөтү', // check with a native speaker
    jobPickDate: 'Күндү тандоо', // check with a native speaker
    jobFill: 'Толтуруңуз: ИИ буйрутманы ушул боюнча табат', // check with a native speaker
    jobsSearch: 'Номер, телефон же аты', // check with a native speaker
    jobsEmpty: 'Иште буйрутма жок.', // check with a native speaker
    jobsExampleBanner: 'Мисалдагы квитанциялар: тесттик чатта ИИ аларды билет, чыныгы кардарларга — жок. Өз буйрутмаларыңызды кабыл ала баштаганда өчүрүңүз.', // check with a native speaker
    jobsExampleConfirm: 'Мисалдагы квитанцияларды өчүрөсүзбү?', // check with a native speaker
    jobTold: 'кардарга жазылды', // check with a native speaker
    jobsDone: _kyJobsDone,
    jobsExampleDeleted: _kyJobsExampleDeleted,
    jobStatus: _kyJobStatus,
    jobDue: _kyJobDue,
    jobAccepted: _kyJobAccepted,
    jobReadyTold: _kyJobReadyTold,
    jobReadyCall: _kyJobReadyCall,
    jobSaved: _kyJobSaved,
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
/// The Russian form after a number: 1 диалог, 2 диалога, 5 диалогов, 11 диалогов, 21 диалог.
String ruForm(int n, String one, String few, String many) {
  final last2 = n.abs() % 100, last = n.abs() % 10;
  if (last == 1 && last2 != 11) return one;
  return last >= 2 && last <= 4 && (last2 < 12 || last2 > 14) ? few : many;
}

String _ruAiFigure(String key, int n) => switch (key) {
      'conversations' => '${ruForm(n, 'диалог', 'диалога', 'диалогов')} с клиентами',
      'off_hours_conversations' => 'из них в нерабочее время',
      'bookings' => '${ruForm(n, 'запись', 'записи', 'записей')} сделал ИИ',
      'off_hours_bookings' => '${ruForm(n, 'запись', 'записи', 'записей')} в нерабочее время',
      'orders' => '${ruForm(n, 'заказ', 'заказа', 'заказов')} принял ИИ',
      'stays' => '${ruForm(n, 'бронь', 'брони', 'броней')} сделал ИИ',
      'requests' => '${ruForm(n, 'заявка', 'заявки', 'заявок')} на запись (перезвонить)',
      'qualified' => '${ruForm(n, 'заявку', 'заявки', 'заявок')} собрал ИИ',
      'handed_to_people' => '${ruForm(n, 'вопрос передан', 'вопроса передано', 'вопросов передано')} людям',
      _ => '',
    };
String _kyAiFigure(String key, int n) => const { // Kyrgyz nouns do not change after a number
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
String _ruDepAwait(String amount, String until) => 'ждём предоплату $amount до $until';
String _kyDepAwait(String amount, String until) => '$amount алдын ала төлөм күтүлүүдө, $until чейин';
String _ruDepCheck(String amount) => 'прислал чек — проверьте $amount';
String _kyDepCheck(String amount) => 'чек жөнөттү — $amount текшериңиз';
String _ruDepPaid(String amount) => 'предоплата $amount получена';
String _kyDepPaid(String amount) => '$amount алдын ала төлөм алынды';
String _ruCustomerLine(int visits, String spent) => 'визитов: $visits · $spent';
String _kyCustomerLine(int visits, String spent) => 'визит: $visits · $spent';
String _ruShownOf(int shown, int total) => 'Показаны $shown из $total — уточните поиск';
String _kyShownOf(int shown, int total) => '$total ичинен $shown көрсөтүлдү — издөөнү тактаңыз';
String _ruHttpsOnly(String server) =>
    'Адрес $server без https: пароль ушёл бы через интернет открытым текстом. Укажите адрес с https:// — http подходит '
    'только для сервера в этой же Wi-Fi сети.';
String _kyHttpsOnly(String server) =>
    '$server дареги https эмес: сырсөз интернет аркылуу ачык кетмек. https:// менен дарек жазыңыз — http ушул эле '
    'Wi-Fi тармагындагы сервер үчүн гана жарайт.';

String _ruStayTitle(String kind) => switch (kind) { 'hall' => 'Брони залов', 'car' => 'Брони машин', _ => 'Брони номеров' };
String _kyStayTitle(String kind) =>
    switch (kind) { 'hall' => 'Залдардын брондоосу', 'car' => 'Унаалардын брондоосу', _ => 'Бөлмөлөрдүн брондоосу' };
String _ruNoStays(String kind) =>
    'Броней пока нет. ИИ бронирует ${switch (kind) { 'hall' => 'залы', 'car' => 'машины', _ => 'номера' }} сам '
    'и не отдаст занятые даты.';
String _kyNoStays(String kind) =>
    'Азырынча брон жок. ИИ ${switch (kind) { 'hall' => 'залдарды', 'car' => 'унааларды', _ => 'бөлмөлөрдү' }} өзү брондойт '
    'жана бош эмес күндөрдү бербейт.';
String _ruNewStays(int n) => n == 1 ? 'Новая бронь' : 'Новых броней: $n';
String _kyNewStays(int n) => n == 1 ? 'Жаңы брон' : 'Жаңы брондор: $n';
String _ruNights(int n) {
  final last = n % 10, lastTwo = n % 100;
  final word = last == 1 && lastTwo != 11
      ? 'ночь'
      : (last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14) ? 'ночи' : 'ночей');
  return '$n $word';
}
String _kyNights(int n) => '$n түн';
String _ruGuests(int n) => 'гостей: $n';
String _kyGuests(int n) => 'конок саны: $n';
String _ruCancelStayQuestion(String who) => who.isEmpty ? 'Отменить бронь?' : 'Отменить бронь: $who?';
String _kyCancelStayQuestion(String who) => who.isEmpty ? 'Брондоону жокко чыгарасызбы?' : '$who: брондоону жокко чыгарасызбы?';
String _ruStayCancelled(String kind) => switch (kind) {
      'hall' => 'Бронь отменена, зал на эту дату снова свободен. Клиенту сообщите сами.',
      'car' => 'Бронь отменена, машина на эти даты снова свободна. Клиенту сообщите сами.',
      _ => 'Бронь отменена, номер на эти даты снова свободен. Гостю сообщите сами.',
    };
String _kyStayCancelled(String kind) => switch (kind) {
      'hall' => 'Брон жокко чыгарылды, зал бул күнгө кайра бош. Кардарга өзүңүз билдириңиз.',
      'car' => 'Брон жокко чыгарылды, унаа бул күндөргө кайра бош. Кардарга өзүңүз билдириңиз.',
      _ => 'Брон жокко чыгарылды, бөлмө бул күндөргө кайра бош. Конокко өзүңүз билдириңиз.',
    };
String _ruStaysCount(int n) => 'Действующих броней: $n';
String _kyStaysCount(int n) => 'Күчүндөгү брондор: $n';
String _ruDays(int n) => 'дней: $n';
String _kyDays(int n) => '$n күн';
String _ruChooseRoom(String kind) => switch (kind) { 'hall' => 'Зал', 'car' => 'Машина', _ => 'Номер' };
String _kyChooseRoom(String kind) => switch (kind) { 'hall' => 'Зал', 'car' => 'Унаа', _ => 'Бөлмө' };
String _ruRoomFree(int n) => n == 0 ? 'занято' : 'свободно: $n';
String _kyRoomFree(int n) => n == 0 ? 'бош эмес' : 'бош: $n';
String _ruStayBooked(String who, String dates) => 'Забронировано: $who, $dates';
String _kyStayBooked(String who, String dates) => 'Брондолду: $who, $dates';

String _ruTrial(int days) => days > 0
    ? '$days ${ruForm(days, 'день', 'дня', 'дней')} бесплатно, без карты. Пример прайса уже заполнен — замените его своим.'
    : 'Пример прайса уже заполнен — замените его своим.';
String _kyTrial(int days) => days > 0
    ? '$days күн акысыз, картасыз. Прайстын үлгүсү толтурулган — өзүңүздүкүнө алмаштырыңыз.' // check with a native speaker
    : 'Прайстын үлгүсү толтурулган — өзүңүздүкүнө алмаштырыңыз.';
String _ruSignUpNext(String login, String setup) =>
    'Ваш логин: $login (или телефон), пароль — тот, что вы ввели. Чтобы ИИ начал отвечать клиентам, подключите '
    'Telegram-бота и проверьте прайс в панели на компьютере: $setup';
String _kySignUpNext(String login, String setup) => // check with a native speaker
    'Логиниңиз: $login (же телефон), сырсөз — сиз жазгандай. ИИ кардарларга жооп бере башташы үчүн компьютердеги '
    'панелде Telegram-ботту туташтырып, прайсты текшериңиз: $setup';

String _ruSetupProgress(int done, int total) => 'Готово $done из $total';
String _kySetupProgress(int done, int total) => '$total кадамдан $done даяр'; // check with a native speaker

String _ruTestBookingsCancelled(int n) => 'Тестовые записи отменены, время снова свободно: $n.';
String _kyTestBookingsCancelled(int n) => 'Сынак жазылуулар жокко чыгарылды, убакыт кайра бош: $n.'; // check with a native speaker

String _ruExampleDeleted(int n) => n == 0 ? 'Примера в прайсе нет.' : 'Пример удалён: $n. Добавьте свои позиции с ценами.';
String _kyExampleDeleted(int n) => n == 0 ? 'Прайста мисал жок.' : 'Мисал өчүрүлдү: $n. Өзүңүздүн позицияларды баалары менен кошуңуз.'; // check with a native speaker

String _ruPeopleExampleDeleted(int n) => n == 0 ? 'Примера здесь нет.' : 'Пример удалён: $n, с их свободными окнами. Добавьте своих.';
String _kyPeopleExampleDeleted(int n) => n == 0 ? 'Бул жерде мисал жок.' : 'Мисал өчүрүлдү: $n, бош убактылары менен. Өзүңүздүкүн кошуңуз.'; // check with a native speaker
String _ruPersonSeats(int n) => 'мест: $n';
String _kyPersonSeats(int n) => 'орун: $n'; // check with a native speaker
String _ruPersonGroupUpTo(int n) => 'группа до $n';
String _kyPersonGroupUpTo(int n) => '$n кишиге чейин топ'; // check with a native speaker
String _ruWindowsOpened(int n) => 'Открыто окон: $n. ИИ уже может записывать в них клиентов.';
String _kyWindowsOpened(int n) => 'Ачылган убакыт: $n. ИИ аларга кардарларды жаза алат.'; // check with a native speaker
String _ruFreeAhead(int n) => n == 0 ? 'свободных окон нет' : 'свободных окон: $n';
String _kyFreeAhead(int n) => n == 0 ? 'бош убакыт жок' : 'бош убакыт: $n'; // check with a native speaker

// «Заказы в работе». The Kyrgyz texts: check with a native speaker.
String _ruJobsDone(bool delivered) => delivered ? 'Доставленные и отменённые' : 'Выданные и отменённые';
String _kyJobsDone(bool delivered) => delivered ? 'Жеткирилгендер жана жокко чыгарылгандар' : 'Берилгендер жана жокко чыгарылгандар';
String _ruJobsExampleDeleted(int n) => n == 0 ? 'Примера здесь нет.' : 'Удалено квитанций из примера: $n.';
String _kyJobsExampleDeleted(int n) => n == 0 ? 'Бул жерде мисал жок.' : 'Мисалдагы квитанциялар өчүрүлдү: $n.';
String _ruJobStatus(String status, bool delivered) => switch (status) {
      'accepted' => 'принят',
      'in_progress' => 'в работе',
      'ready' => delivered ? 'готов, согласуем доставку' : 'готов, можно забирать',
      'issued' => delivered ? 'доставлен' : 'выдан',
      'cancelled' => 'отменён',
      _ => status,
    };
String _kyJobStatus(String status, bool delivered) => switch (status) {
      'accepted' => 'кабыл алынды',
      'in_progress' => 'иштелүүдө',
      'ready' => delivered ? 'даяр, жеткирүүнү макулдашабыз' : 'даяр, алып кетсе болот',
      'issued' => delivered ? 'жеткирилди' : 'берилди',
      'cancelled' => 'жокко чыгарылды',
      _ => status,
    };
String _ruJobDue(String day) => 'срок $day';
String _kyJobDue(String day) => 'мөөнөтү $day';
String _ruJobAccepted(String number) =>
    'Заказ №$number принят. Назовите клиенту номер квитанции: по нему и телефону ИИ ответит, готово ли.';
String _kyJobAccepted(String number) =>
    '№$number буйрутма кабыл алынды. Кардарга квитанциянын номерин айтыңыз: ал жана телефон боюнча ИИ даярбы деп жооп берет.';
String _ruJobReadyTold(String number) => 'Заказ №$number готов. Клиенту отправлено сообщение.';
String _kyJobReadyTold(String number) => '№$number буйрутма даяр. Кардарга билдирүү жөнөтүлдү.';
String _ruJobReadyCall(String number, String phone) =>
    'Заказ №$number готов. Написать клиенту не получилось: нет чата с ним или в WhatsApp прошло больше суток. Позвоните: $phone';
String _kyJobReadyCall(String number, String phone) =>
    '№$number буйрутма даяр. Кардарга жазуу мүмкүн болгон жок: аны менен чат жок же WhatsApp аркылуу бир суткадан ашык жазышкан жок. Чалыңыз: $phone';
String _ruJobSaved(String number, String status) => 'Заказ №$number: $status.';
String _kyJobSaved(String number, String status) => '№$number буйрутма: $status.';
