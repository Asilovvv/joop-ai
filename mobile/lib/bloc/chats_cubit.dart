import 'package:equatable/equatable.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../core/api_client.dart';
import '../data/joop_repository.dart';
import '../data/models.dart';
import 'load_status.dart';

class ChatsState extends Equatable {
  const ChatsState({this.status = LoadStatus.initial, this.chats = const [], this.query = '', this.error});

  final LoadStatus status;
  final List<ChatSummary> chats;
  final String query;
  final String? error;

  @override
  List<Object?> get props => [status, chats, query, error];
}

/// The latest real chats, or those matching a name or phone.
class ChatsCubit extends Cubit<ChatsState> {
  ChatsCubit(this._repository) : super(const ChatsState());

  final JoopRepository _repository;

  Future<void> load([String? query]) async {
    final q = (query ?? state.query).trim();
    emit(ChatsState(status: LoadStatus.loading, chats: state.chats, query: q));
    try {
      final chats = await _repository.chats(query: q);
      if (state.query != q) return; // a newer search is on its way
      emit(ChatsState(status: LoadStatus.success, chats: chats, query: q));
    } on ApiException catch (e) {
      if (state.query != q) return;
      emit(ChatsState(status: LoadStatus.failure, chats: state.chats, query: q, error: e.message));
    }
  }
}
