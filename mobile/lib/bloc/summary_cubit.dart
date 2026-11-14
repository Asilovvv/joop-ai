import 'package:equatable/equatable.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../core/api_client.dart';
import '../data/joop_repository.dart';
import '../data/models.dart';
import 'load_status.dart';

class SummaryState extends Equatable {
  const SummaryState({this.status = LoadStatus.initial, this.summary, this.error});

  final LoadStatus status;
  final Summary? summary;
  final String? error;

  @override
  List<Object?> get props => [status, summary, error];
}

/// The home screen's counts: bookings today, tomorrow, this week, and the next visit.
class SummaryCubit extends Cubit<SummaryState> {
  SummaryCubit(this._repository) : super(const SummaryState());

  final JoopRepository _repository;

  /// A background check: keeps the shown numbers while asking, and keeps them when the check fails.
  Future<void> refresh() async {
    if (state.status == LoadStatus.loading) return;
    try {
      emit(SummaryState(status: LoadStatus.success, summary: await _repository.summary()));
    } on ApiException {
      // The next check tries again.
    }
  }

  Future<void> load() async {
    emit(SummaryState(status: LoadStatus.loading, summary: state.summary));
    try {
      emit(SummaryState(status: LoadStatus.success, summary: await _repository.summary()));
    } on ApiException catch (e) {
      emit(SummaryState(status: LoadStatus.failure, summary: state.summary, error: e.message));
    }
  }
}
