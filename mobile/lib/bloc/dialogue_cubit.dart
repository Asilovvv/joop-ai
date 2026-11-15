import 'package:equatable/equatable.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../core/api_client.dart';
import '../core/strings.dart';
import '../data/joop_repository.dart';
import '../data/models.dart';
import 'load_status.dart';

class DialogueState extends Equatable {
  const DialogueState({this.status = LoadStatus.initial, this.dialogue, this.sending = false, this.error, this.notice});

  final LoadStatus status;
  final Dialogue? dialogue;
  final bool sending;
  final String? error;
  final String? notice;

  @override
  List<Object?> get props => [status, dialogue, sending, error, notice];
}

/// One customer's dialogue, and the owner's reply to it through the customer's channel.
class DialogueCubit extends Cubit<DialogueState> {
  DialogueCubit(this._repository, this.conversationId) : super(const DialogueState());

  final JoopRepository _repository;
  final int conversationId;

  Future<void> load() async {
    emit(DialogueState(status: LoadStatus.loading, dialogue: state.dialogue));
    try {
      emit(DialogueState(status: LoadStatus.success, dialogue: await _repository.dialogue(conversationId)));
    } on ApiException catch (e) {
      emit(DialogueState(status: LoadStatus.failure, dialogue: state.dialogue, error: e.message));
    }
  }

  Future<void> switchAi(bool on) async {
    if (state.dialogue == null || state.sending) return;
    emit(DialogueState(status: state.status, dialogue: state.dialogue, sending: true));
    try {
      final dialogue = await _repository.switchAi(conversationId, on);
      emit(DialogueState(
          status: LoadStatus.success, dialogue: dialogue, notice: on ? S.current.aiOnDone : S.current.aiOffDone));
    } on ApiException catch (e) {
      emit(DialogueState(status: state.status, dialogue: state.dialogue, error: e.message));
    }
  }

  /// True when the reply went out; the text stays in the box otherwise.
  Future<bool> reply(String text) async {
    if (text.trim().isEmpty || state.sending) return false;
    emit(DialogueState(status: state.status, dialogue: state.dialogue, sending: true));
    try {
      final dialogue = await _repository.reply(conversationId, text.trim());
      emit(DialogueState(status: LoadStatus.success, dialogue: dialogue, notice: S.current.answerSent));
      return true;
    } on ApiException catch (e) {
      emit(DialogueState(status: state.status, dialogue: state.dialogue, error: e.message));
      return false;
    }
  }
}
