import 'dart:async';

import 'package:equatable/equatable.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../core/api_client.dart';
import '../data/customer_repository.dart';
import '../data/models.dart';

// ---------------------------------------------------------------- events

sealed class ChatEvent extends Equatable {
  const ChatEvent();

  @override
  List<Object?> get props => [];
}

/// The chat screen opened: load the saved messages and start asking for staff replies.
final class ChatOpened extends ChatEvent {
  const ChatOpened();
}

final class ChatMessageSent extends ChatEvent {
  const ChatMessageSent(this.text);

  final String text;

  @override
  List<Object?> get props => [text];
}

/// Ask the server for replies staff wrote from the panel.
final class ChatPolled extends ChatEvent {
  const ChatPolled();
}

// ---------------------------------------------------------------- state

class ChatState extends Equatable {
  const ChatState({this.messages = const [], this.waiting = false, this.error});

  final List<ChatMessage> messages;

  /// The AI is answering.
  final bool waiting;
  final String? error;

  int get lastStaffId => messages.fold(0, (last, m) => m.staffId != null && m.staffId! > last ? m.staffId! : last);

  @override
  List<Object?> get props => [messages, waiting, error];
}

// ------------------------------------------------------------------ bloc

/// A chat with one business's AI administrator: it answers prices, free time and books, as in WhatsApp.
class ChatBloc extends Bloc<ChatEvent, ChatState> {
  ChatBloc(this._repository, this.slug, {Duration poll = const Duration(seconds: 15)}) : super(const ChatState()) {
    on<ChatOpened>(_onOpened);
    on<ChatMessageSent>(_onSent);
    on<ChatPolled>(_onPolled);
    if (poll > Duration.zero) _timer = Timer.periodic(poll, (_) => add(const ChatPolled()));
  }

  final CustomerRepository _repository;
  final String slug;
  Timer? _timer;

  Future<void> _onOpened(ChatOpened event, Emitter<ChatState> emit) async {
    emit(ChatState(messages: await _repository.history(slug)));
    add(const ChatPolled());
  }

  Future<void> _onSent(ChatMessageSent event, Emitter<ChatState> emit) async {
    final text = event.text.trim();
    if (text.isEmpty || state.waiting) return;
    final asked = [...state.messages, ChatMessage(fromCustomer: true, text: text)];
    emit(ChatState(messages: asked, waiting: true));
    try {
      final reply = await _repository.send(slug, text);
      final messages = [...asked, if (reply.isNotEmpty) ChatMessage(fromCustomer: false, text: reply)];
      emit(ChatState(messages: messages));
      await _repository.saveHistory(slug, messages);
    } on ApiException catch (e) {
      emit(ChatState(messages: asked, error: e.message));
      await _repository.saveHistory(slug, asked);
    }
  }

  Future<void> _onPolled(ChatPolled event, Emitter<ChatState> emit) async {
    try {
      final fresh = await _repository.updates(slug, state.lastStaffId);
      if (fresh.isEmpty) return;
      final messages = [...state.messages, ...fresh];
      emit(ChatState(messages: messages, waiting: state.waiting));
      await _repository.saveHistory(slug, messages);
    } on ApiException {
      // Staff replies are a bonus: a missed poll is retried by the next one.
    }
  }

  @override
  Future<void> close() {
    _timer?.cancel();
    return super.close();
  }
}
