import 'package:equatable/equatable.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../core/api_client.dart';
import '../data/joop_repository.dart';
import '../data/models.dart';

class CashState extends Equatable {
  const CashState({this.day, this.failed = false});

  final CashDay? day;
  final bool failed;

  @override
  List<Object?> get props => [day, failed];
}

/// Today's takings for the home screen. A failed check keeps the numbers already shown.
class CashCubit extends Cubit<CashState> {
  CashCubit(this._repository, this.today) : super(const CashState());

  final JoopRepository _repository;
  final DateTime today;

  Future<void> load() async {
    try {
      emit(CashState(day: await _repository.cash(today)));
    } on ApiException {
      emit(CashState(day: state.day, failed: true));
    }
  }
}
