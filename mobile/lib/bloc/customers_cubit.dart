import 'package:equatable/equatable.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../core/api_client.dart';
import '../data/joop_repository.dart';
import '../data/models.dart';
import 'load_status.dart';

class CustomersState extends Equatable {
  const CustomersState({
    this.status = LoadStatus.initial,
    this.rows = const [],
    this.total = 0,
    this.tags = const [],
    this.query = '',
    this.tag = '',
    this.error,
  });

  final LoadStatus status;
  final List<CustomerRow> rows;
  final int total;
  final List<String> tags;
  final String query;
  final String tag;
  final String? error;

  @override
  List<Object?> get props => [status, rows, total, tags, query, tag, error];
}

/// The customers list: a name or phone, and a tag, narrow it.
class CustomersCubit extends Cubit<CustomersState> {
  CustomersCubit(this._repository) : super(const CustomersState());

  final JoopRepository _repository;

  Future<void> load({String? query, String? tag}) async {
    final q = (query ?? state.query).trim();
    final t = tag ?? state.tag;
    emit(CustomersState(
        status: LoadStatus.loading, rows: state.rows, total: state.total, tags: state.tags, query: q, tag: t));
    try {
      final (rows, total, tags) = await _repository.customers(query: q, tag: t);
      if (state.query != q || state.tag != t) return; // a newer search is on its way
      emit(CustomersState(status: LoadStatus.success, rows: rows, total: total, tags: tags, query: q, tag: t));
    } on ApiException catch (e) {
      if (state.query != q || state.tag != t) return;
      emit(CustomersState(
          status: LoadStatus.failure,
          rows: state.rows,
          total: state.total,
          tags: state.tags,
          query: q,
          tag: t,
          error: e.message));
    }
  }
}
