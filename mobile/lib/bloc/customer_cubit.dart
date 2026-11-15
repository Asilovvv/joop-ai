import 'package:equatable/equatable.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../core/api_client.dart';
import '../core/strings.dart';
import '../data/joop_repository.dart';
import '../data/models.dart';
import 'load_status.dart';

class CustomerState extends Equatable {
  const CustomerState({this.status = LoadStatus.initial, this.card, this.saving = false, this.error, this.notice});

  final LoadStatus status;
  final CustomerCard? card;
  final bool saving;
  final String? error;
  final String? notice;

  @override
  List<Object?> get props => [status, card, saving, error, notice];
}

/// One customer's card, and the note and tags staff keep on it.
class CustomerCubit extends Cubit<CustomerState> {
  CustomerCubit(this._repository, this.customerKey) : super(const CustomerState());

  final JoopRepository _repository;
  final String customerKey;

  Future<void> load() async {
    emit(CustomerState(status: LoadStatus.loading, card: state.card));
    try {
      emit(CustomerState(status: LoadStatus.success, card: await _repository.customer(customerKey)));
    } on ApiException catch (e) {
      emit(CustomerState(status: LoadStatus.failure, card: state.card, error: e.message));
    }
  }

  Future<void> saveNote(String note, String tags) async {
    final card = state.card;
    if (card == null || state.saving) return;
    emit(CustomerState(status: state.status, card: card, saving: true));
    try {
      final (savedNote, savedTags) = await _repository.saveNote(customerKey, note, tags);
      emit(CustomerState(status: state.status, card: card.withNote(savedNote, savedTags), notice: S.current.noteSaved));
    } on ApiException catch (e) {
      emit(CustomerState(status: state.status, card: card, notice: e.message));
    }
  }
}
